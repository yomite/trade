"""Integration tests for the TimescaleDB storage layer (Section 11).

Run with a live local database: `pytest -m integration`. Uses a synthetic
symbol and cleans up after itself so real data is never touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.common.types import Bar, FeatureRow, OrderBookSnapshot, Side, Trade
from src.data.storage.timescale import Database

TEST_SYMBOL = "TEST/USDT"
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _cleanup(db: Database) -> Iterator[None]:
    def _wipe() -> None:
        with db.connect() as conn, conn.cursor() as cur:
            for table in ("bars", "trades_raw", "orderbook_snapshots", "features"):
                cur.execute(f"DELETE FROM {table} WHERE symbol = %s", (TEST_SYMBOL,))

    _wipe()
    yield
    _wipe()


def _bar(ts: datetime, close: str) -> Bar:
    return Bar(
        symbol=TEST_SYMBOL,
        timeframe="1m",
        ts=ts,
        open=Decimal("100.0"),
        high=Decimal("101.5"),
        low=Decimal("99.5"),
        close=Decimal(close),
        volume=Decimal("12.34567"),
        trades=42,
    )


def test_bars_roundtrip_preserves_decimals(db: Database) -> None:
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    bars = [_bar(t0 + timedelta(minutes=i), close=f"100.{i:02d}") for i in range(5)]
    assert db.upsert_bars(bars) == 5

    fetched = db.fetch_bars(TEST_SYMBOL, "1m")
    assert len(fetched) == 5
    assert fetched[0].close == Decimal("100.00")
    assert fetched[4].close == Decimal("100.04")
    assert fetched[0].volume == Decimal("12.34567")  # exact, no float drift
    assert db.count_bars(TEST_SYMBOL, "1m") == 5
    assert db.latest_bar_ts(TEST_SYMBOL, "1m") == t0 + timedelta(minutes=4)


def test_bars_upsert_is_idempotent(db: Database) -> None:
    t0 = datetime(2025, 2, 1, tzinfo=UTC)
    db.upsert_bars([_bar(t0, "200.0")])
    db.upsert_bars([_bar(t0, "250.0")])  # same key, new close
    fetched = db.fetch_bars(TEST_SYMBOL, "1m")
    assert len(fetched) == 1
    assert fetched[0].close == Decimal("250.0")


def test_trades_insert_dedupes(db: Database) -> None:
    t0 = datetime(2025, 3, 1, tzinfo=UTC)
    trades = [
        Trade(TEST_SYMBOL, t0, Decimal("100.1"), Decimal("0.5"), Side.BUY, "t1"),
        Trade(TEST_SYMBOL, t0, Decimal("100.2"), Decimal("0.6"), Side.SELL, "t2"),
    ]
    assert db.insert_trades(trades) == 2
    # Re-inserting the same trade_ids must not create duplicates.
    db.insert_trades(trades)
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM trades_raw WHERE symbol = %s", (TEST_SYMBOL,))
        row = cur.fetchone()
    assert row is not None
    assert row[0] == 2


def test_orderbook_and_features_write(db: Database) -> None:
    t0 = datetime(2025, 4, 1, tzinfo=UTC)
    snap = OrderBookSnapshot(
        symbol=TEST_SYMBOL,
        ts=t0,
        bids=[(Decimal("100.0"), Decimal("1.0")), (Decimal("99.9"), Decimal("2.0"))],
        asks=[(Decimal("100.1"), Decimal("1.5"))],
    )
    assert db.insert_orderbook([snap]) == 1

    feat = FeatureRow(
        symbol=TEST_SYMBOL,
        timeframe="1m",
        ts=t0,
        feature_set="v1",
        values={"rsi_14": 57.5, "ret_1": -0.0012},
    )
    assert db.upsert_features([feat]) == 1
    with db.connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT values FROM features WHERE symbol = %s AND feature_set = 'v1'",
            (TEST_SYMBOL,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0]["rsi_14"] == 57.5
