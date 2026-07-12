"""Bybit v5 REST client + historical kline loader (Layer 1, Section 5.1).

Fetches 1m (and other timeframe) OHLCV candles for backfill. Public market-data
endpoints need no API key.

Host fallback: ``api.bybit.com`` is DNS-blocked on some networks (including the
operator's), so the client tries a list of hosts and sticks with the first that
answers. ``api.bytick.com`` is Bybit's official mirror and is the working host
on the dev machine. The host list is configurable so the droplet can prefer the
primary.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from src.common.logging import get_logger
from src.common.time import from_ms, now, to_ms
from src.common.types import Bar

log = get_logger("ingestion.bybit_rest")

# Ordered by preference; the client sticks to the first that resolves/answers.
DEFAULT_HOSTS: tuple[str, ...] = ("api.bybit.com", "api.bytick.com")

# CLAUDE.md timeframe -> Bybit v5 kline `interval` code and its width in ms.
_INTERVAL_CODE: dict[str, str] = {"1m": "1", "5m": "5", "15m": "15", "1h": "60", "4h": "240"}
_INTERVAL_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
}
_MAX_LIMIT = 1000  # Bybit's max klines per request


class BybitRestError(RuntimeError):
    """Raised when Bybit returns an error or no host is reachable."""


def to_bybit_symbol(symbol: str) -> str:
    """'BTC/USDT' -> 'BTCUSDT' (Bybit's symbol format)."""
    return symbol.replace("/", "")


def parse_kline_list(symbol: str, timeframe: str, rows: list[list[str]]) -> list[Bar]:
    """Parse Bybit kline rows into Bars, oldest-first.

    Each row is ``[startMs, open, high, low, close, volume, turnover]`` (strings).
    Bybit returns newest-first; we reverse to ascending ts.
    """
    bars = [
        Bar(
            symbol=symbol,
            timeframe=timeframe,
            ts=from_ms(int(r[0])),
            open=Decimal(r[1]),
            high=Decimal(r[2]),
            low=Decimal(r[3]),
            close=Decimal(r[4]),
            volume=Decimal(r[5]),
        )
        for r in rows
    ]
    bars.sort(key=lambda b: b.ts)
    return bars


class BybitREST:
    """Minimal synchronous Bybit v5 market-data client for backfills."""

    def __init__(
        self,
        hosts: tuple[str, ...] = DEFAULT_HOSTS,
        category: str = "spot",
        timeout: float = 20.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._hosts = hosts
        self._category = category
        self._client = client or httpx.Client(timeout=timeout)
        self._active_host: str | None = None

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BybitREST:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, BybitRestError)),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET with host fallback and retry (Section 21.2)."""
        hosts = [self._active_host] if self._active_host else list(self._hosts)
        last_err: Exception | None = None
        for host in hosts:
            if host is None:
                continue
            try:
                resp = self._client.get(f"https://{host}{path}", params=params)
                resp.raise_for_status()
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # DNS block / unreachable host — try the next mirror.
                log.warning("host_unreachable", host=host, error=type(exc).__name__)
                last_err = exc
                continue
            payload: dict[str, Any] = resp.json()
            if payload.get("retCode") != 0:
                raise BybitRestError(
                    f"Bybit error {payload.get('retCode')}: {payload.get('retMsg')}"
                )
            self._active_host = host  # stick to the working host
            return payload
        raise BybitRestError(f"no reachable Bybit host among {self._hosts}") from last_err

    def fetch_klines(
        self, symbol: str, timeframe: str, start_ms: int, end_ms: int, limit: int = _MAX_LIMIT
    ) -> list[Bar]:
        """Fetch up to ``limit`` klines in [start_ms, end_ms), ascending ts."""
        if timeframe not in _INTERVAL_CODE:
            raise BybitRestError(f"unsupported timeframe {timeframe!r}")
        payload = self._get(
            "/v5/market/kline",
            {
                "category": self._category,
                "symbol": to_bybit_symbol(symbol),
                "interval": _INTERVAL_CODE[timeframe],
                "start": start_ms,
                "end": end_ms,
                "limit": limit,
            },
        )
        rows: list[list[str]] = payload["result"].get("list", [])
        return parse_kline_list(symbol, timeframe, rows)

    def iter_klines_range(
        self, symbol: str, timeframe: str, start_ms: int, end_ms: int
    ) -> Iterator[list[Bar]]:
        """Yield successive batches of klines covering [start_ms, end_ms).

        Pages forward in windows of ``_MAX_LIMIT`` bars — one request per window,
        so termination is guaranteed even across gaps. Duplicate boundary bars are
        harmless (the writer upserts).
        """
        step = _INTERVAL_MS[timeframe]
        window = _MAX_LIMIT * step
        cursor = start_ms
        while cursor < end_ms:
            window_end = min(cursor + window, end_ms)
            batch = self.fetch_klines(symbol, timeframe, cursor, window_end)
            if batch:
                yield batch
            cursor = window_end


def default_history_start_ms(years: int = 5) -> int:
    """Epoch-ms for `years` before now (Section 5.1: 5 years of 1m data)."""
    return to_ms(now()) - years * 365 * 24 * 60 * 60 * 1000
