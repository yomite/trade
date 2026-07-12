"""TimescaleDB connection and writers (Section 11, Layer 1).

Reads ``DATABASE_URL`` from the environment (secrets never live in config files,
Section 12.3). Prices/quantities are written as ``NUMERIC`` from ``Decimal`` —
psycopg2 adapts ``Decimal`` to ``NUMERIC`` natively, preserving exactness.

Writers are idempotent: bars and features upsert on their primary key, trades and
order book snapshots use ``ON CONFLICT DO NOTHING`` so replays never duplicate.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extensions import connection as PgConnection  # noqa: N812 (type alias)
from psycopg2.extras import execute_values

from src.common.logging import get_logger
from src.common.types import Bar, FeatureRow, OrderBookSnapshot, Trade

log = get_logger("storage.timescale")

_SCHEMA_FILENAME = "schema.sql"


class DatabaseError(RuntimeError):
    """Raised for unrecoverable database problems (fail loud, Section 2.5)."""


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseError("DATABASE_URL is not set in the environment")
    return url


class Database:
    """Thin wrapper over a psycopg2 connection factory.

    Not a pool — Layer 1 ingestion opens short-lived connections per batch. A
    pool can be added later if contention appears; the interface stays the same.
    """

    def __init__(self, url: str | None = None) -> None:
        self._url = url or _database_url()

    @contextmanager
    def connect(self) -> Iterator[PgConnection]:
        """Yield a connection, committing on success and rolling back on error."""
        conn = psycopg2.connect(self._url, connect_timeout=10)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -- schema ---------------------------------------------------------------

    def apply_schema(self, schema_path: Path | None = None) -> None:
        """Create all tables and hypertables (idempotent)."""
        sql = (
            schema_path.read_text(encoding="utf-8")
            if schema_path is not None
            else resources.files("src.data.storage").joinpath(_SCHEMA_FILENAME).read_text()
        )
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
        log.info("schema_applied")

    def ping(self) -> bool:
        """Return True if the database answers and TimescaleDB is installed."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';")
            row = cur.fetchone()
        return row is not None

    # -- writers --------------------------------------------------------------

    def upsert_bars(self, bars: Sequence[Bar]) -> int:
        """Insert/replace OHLCV bars keyed by (symbol, timeframe, ts)."""
        if not bars:
            return 0
        rows = [
            (b.symbol, b.timeframe, b.ts, b.open, b.high, b.low, b.close, b.volume, b.trades)
            for b in bars
        ]
        sql = """
            INSERT INTO bars (symbol, timeframe, ts, open, high, low, close, volume, trades)
            VALUES %s
            ON CONFLICT (symbol, timeframe, ts) DO UPDATE SET
                open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                close = EXCLUDED.close, volume = EXCLUDED.volume, trades = EXCLUDED.trades
        """
        return self._execute_values(sql, rows)

    def insert_trades(self, trades: Sequence[Trade]) -> int:
        """Insert tick trades; duplicates (same symbol/ts/trade_id) are ignored."""
        if not trades:
            return 0
        rows = [(t.symbol, t.ts, t.price, t.size, t.side.value, t.trade_id) for t in trades]
        sql = """
            INSERT INTO trades_raw (symbol, ts, price, size, side, trade_id)
            VALUES %s
            ON CONFLICT (symbol, ts, trade_id) DO NOTHING
        """
        return self._execute_values(sql, rows)

    def insert_orderbook(self, snapshots: Sequence[OrderBookSnapshot]) -> int:
        """Insert order book snapshots; duplicates (symbol, ts) are ignored."""
        if not snapshots:
            return 0
        rows = [
            (s.symbol, s.ts, json.dumps(_levels(s.bids)), json.dumps(_levels(s.asks)))
            for s in snapshots
        ]
        sql = """
            INSERT INTO orderbook_snapshots (symbol, ts, bids, asks)
            VALUES %s
            ON CONFLICT (symbol, ts) DO NOTHING
        """
        return self._execute_values(sql, rows)

    def upsert_features(self, features: Sequence[FeatureRow]) -> int:
        """Insert/replace feature vectors keyed by (symbol, timeframe, ts, set)."""
        if not features:
            return 0
        rows = [
            (f.symbol, f.timeframe, f.ts, f.feature_set, json.dumps(f.values)) for f in features
        ]
        sql = """
            INSERT INTO features (symbol, timeframe, ts, feature_set, values)
            VALUES %s
            ON CONFLICT (symbol, timeframe, ts, feature_set) DO UPDATE SET
                values = EXCLUDED.values
        """
        return self._execute_values(sql, rows)

    def log_ingestion(
        self,
        source: str,
        symbol: str,
        timeframe: str,
        ts_start: datetime,
        ts_end: datetime,
        rows: int,
        gaps: int = 0,
    ) -> None:
        """Record a completed ingestion window for auditability / resumption."""
        sql = """
            INSERT INTO ingestion_log (source, symbol, timeframe, ts_start, ts_end, rows, gaps)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, symbol, timeframe, ts_start) DO UPDATE SET
                ts_end = EXCLUDED.ts_end, rows = EXCLUDED.rows, gaps = EXCLUDED.gaps
        """
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (source, symbol, timeframe, ts_start, ts_end, rows, gaps))

    # -- readers --------------------------------------------------------------

    def latest_bar_ts(self, symbol: str, timeframe: str) -> datetime | None:
        """Timestamp of the most recent stored bar, or None if none exist."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT max(ts) FROM bars WHERE symbol = %s AND timeframe = %s",
                (symbol, timeframe),
            )
            row = cur.fetchone()
        return row[0] if row and row[0] is not None else None

    def count_bars(self, symbol: str, timeframe: str) -> int:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM bars WHERE symbol = %s AND timeframe = %s",
                (symbol, timeframe),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0

    def bar_span(self, symbol: str, timeframe: str) -> tuple[datetime | None, datetime | None, int]:
        """(earliest ts, latest ts, count) for a symbol/timeframe."""
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT min(ts), max(ts), count(*) FROM bars WHERE symbol = %s AND timeframe = %s",
                (symbol, timeframe),
            )
            row = cur.fetchone()
        if not row:
            return None, None, 0
        return row[0], row[1], int(row[2])

    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Bar]:
        """Return bars for a symbol/timeframe in ascending ts order."""
        clauses = ["symbol = %s", "timeframe = %s"]
        params: list[Any] = [symbol, timeframe]
        if start is not None:
            clauses.append("ts >= %s")
            params.append(start)
        if end is not None:
            clauses.append("ts < %s")
            params.append(end)
        sql = (
            "SELECT symbol, timeframe, ts, open, high, low, close, volume, trades "
            "FROM bars WHERE " + " AND ".join(clauses) + " ORDER BY ts ASC"
        )
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            fetched = cur.fetchall()
        return [
            Bar(
                symbol=r[0],
                timeframe=r[1],
                ts=r[2],
                open=_dec(r[3]),
                high=_dec(r[4]),
                low=_dec(r[5]),
                close=_dec(r[6]),
                volume=_dec(r[7]),
                trades=r[8],
            )
            for r in fetched
        ]

    # -- internal -------------------------------------------------------------

    def _execute_values(self, sql: str, rows: Sequence[tuple[Any, ...]]) -> int:
        with self.connect() as conn, conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=1000)
            return len(rows)


def _levels(levels: list[tuple[Decimal, Decimal]]) -> list[list[str]]:
    # Store Decimals as strings in JSONB to avoid float rounding.
    return [[str(price), str(size)] for price, size in levels]


def _dec(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))
