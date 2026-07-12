"""Bybit v5 live websocket feed (Layer 1, Section 5.1).

Subscribes to confirmed 1m klines, public trades, and the order book for each
symbol and writes them to TimescaleDB. Built on pybit's threaded WebSocket.

Host: ``stream.bybit.com`` is DNS-blocked on some networks, so the domain is
auto-detected (``bybit`` -> ``bytick``) exactly like the REST client.

Writes are batched/throttled to keep DB load sane:
- **klines**: written on candle close (``confirm`` = True) — one per minute/symbol
- **trades**: buffered, flushed every ``TRADE_FLUSH_SECONDS`` or ``TRADE_FLUSH_MAX``
- **order book**: maintained from snapshot+delta, snapshotted at ``OB_SNAPSHOT_SECONDS``
"""

from __future__ import annotations

import socket
import threading
from decimal import Decimal
from typing import Any

from pybit.unified_trading import WebSocket

from src.common.logging import get_logger
from src.common.time import from_ms, now
from src.common.types import Bar, OrderBookSnapshot, Side, Trade
from src.data.ingestion.bybit_rest import to_bybit_symbol
from src.data.storage.timescale import Database

log = get_logger("ingestion.bybit_ws")

TRADE_FLUSH_SECONDS = 5.0
TRADE_FLUSH_MAX = 200
OB_SNAPSHOT_SECONDS = 1.0
OB_DEPTH = 50  # subscribe depth; we store the top 20 (Section 11)
OB_STORE_LEVELS = 20


def pick_ws_domain(preferred: tuple[str, ...] = ("bybit", "bytick")) -> str:
    """Return the first stream host domain that resolves (bybit, else bytick)."""
    for domain in preferred:
        try:
            socket.getaddrinfo(f"stream.{domain}.com", 443)
            return domain
        except socket.gaierror:
            continue
    return preferred[-1]


class _OrderBook:
    """Maintains one symbol's book from snapshot/delta messages."""

    def __init__(self) -> None:
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}

    def apply(self, data: dict[str, Any], is_snapshot: bool) -> None:
        if is_snapshot:
            self.bids.clear()
            self.asks.clear()
        _apply_side(self.bids, data.get("b", []))
        _apply_side(self.asks, data.get("a", []))

    def snapshot(self, symbol: str) -> OrderBookSnapshot:
        bids = sorted(self.bids.items(), key=lambda kv: kv[0], reverse=True)[:OB_STORE_LEVELS]
        asks = sorted(self.asks.items(), key=lambda kv: kv[0])[:OB_STORE_LEVELS]
        return OrderBookSnapshot(symbol=symbol, ts=now(), bids=bids, asks=asks)


def _apply_side(side: dict[Decimal, Decimal], levels: list[list[str]]) -> None:
    for price_s, size_s in levels:
        price, size = Decimal(price_s), Decimal(size_s)
        if size == 0:
            side.pop(price, None)
        else:
            side[price] = size


class BybitWebsocketFeed:
    """Threaded live feed writing bars, trades, and order books to the database."""

    def __init__(
        self,
        symbols: list[str],
        db: Database | None = None,
        domain: str | None = None,
    ) -> None:
        self._symbols = symbols
        self._db = db or Database()
        self._domain = domain or pick_ws_domain()
        self._ws: WebSocket | None = None
        self._lock = threading.Lock()
        self._trade_buf: list[Trade] = []
        self._last_trade_flush = now()
        self._books: dict[str, _OrderBook] = {s: _OrderBook() for s in symbols}
        self._last_ob_write: dict[str, Any] = dict.fromkeys(symbols)

    def start(self) -> None:
        """Open the socket and subscribe all streams (returns immediately)."""
        self._db.apply_schema()
        self._ws = WebSocket(testnet=False, channel_type="spot", domain=self._domain)
        for symbol in self._symbols:
            bybit_symbol = to_bybit_symbol(symbol)
            self._ws.kline_stream(
                interval=1, symbol=bybit_symbol, callback=self._make_kline_cb(symbol)
            )
            self._ws.trade_stream(symbol=bybit_symbol, callback=self._make_trade_cb(symbol))
            self._ws.orderbook_stream(
                depth=OB_DEPTH, symbol=bybit_symbol, callback=self._make_ob_cb(symbol)
            )
        log.info("ws_started", symbols=self._symbols, domain=self._domain)

    def stop(self) -> None:
        self._flush_trades(force=True)
        if self._ws is not None:
            self._ws.exit()
        log.info("ws_stopped")

    # -- callbacks ------------------------------------------------------------

    def _make_kline_cb(self, symbol: str) -> Any:
        def cb(message: dict[str, Any]) -> None:
            try:
                for k in message.get("data", []):
                    if not k.get("confirm"):
                        continue  # only write closed candles (no partial bars)
                    bar = Bar(
                        symbol=symbol,
                        timeframe="1m",
                        ts=from_ms(int(k["start"])),
                        open=Decimal(str(k["open"])),
                        high=Decimal(str(k["high"])),
                        low=Decimal(str(k["low"])),
                        close=Decimal(str(k["close"])),
                        volume=Decimal(str(k["volume"])),
                    )
                    self._db.upsert_bars([bar])
                    log.info("bar", symbol=symbol, ts=bar.ts.isoformat(), close=str(bar.close))
            except Exception:
                log.exception("kline_cb_error", symbol=symbol)

        return cb

    def _make_trade_cb(self, symbol: str) -> Any:
        def cb(message: dict[str, Any]) -> None:
            try:
                new = [
                    Trade(
                        symbol=symbol,
                        ts=from_ms(int(t["T"])),
                        price=Decimal(str(t["p"])),
                        size=Decimal(str(t["v"])),
                        side=Side.BUY if t["S"].lower() == "buy" else Side.SELL,
                        trade_id=str(t["i"]),
                    )
                    for t in message.get("data", [])
                ]
                with self._lock:
                    self._trade_buf.extend(new)
                self._flush_trades()
            except Exception:
                log.exception("trade_cb_error", symbol=symbol)

        return cb

    def _make_ob_cb(self, symbol: str) -> Any:
        def cb(message: dict[str, Any]) -> None:
            try:
                is_snapshot = message.get("type") == "snapshot"
                self._books[symbol].apply(message.get("data", {}), is_snapshot)
                last = self._last_ob_write[symbol]
                current = now()
                if last is None or (current - last).total_seconds() >= OB_SNAPSHOT_SECONDS:
                    self._db.insert_orderbook([self._books[symbol].snapshot(symbol)])
                    self._last_ob_write[symbol] = current
            except Exception:
                log.exception("ob_cb_error", symbol=symbol)

        return cb

    def _flush_trades(self, force: bool = False) -> None:
        with self._lock:
            due = force or len(self._trade_buf) >= TRADE_FLUSH_MAX
            due = due or (now() - self._last_trade_flush).total_seconds() >= TRADE_FLUSH_SECONDS
            if not due or not self._trade_buf:
                return
            batch, self._trade_buf = self._trade_buf, []
            self._last_trade_flush = now()
        self._db.insert_trades(batch)
