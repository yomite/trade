"""Feature-transform tests: determinism (Phase 1 DoD) and correctness."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.common.types import Bar, OrderBookSnapshot
from src.data.features.indicators import rsi
from src.data.features.orderbook import imbalance, orderbook_features, spread_bps
from src.data.features.pipeline import bars_to_frame, compute_features, feature_rows

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def make_bars(n: int = 300, seed: int = 7) -> list[Bar]:
    """Deterministic synthetic 1m bars (same seed => identical output)."""
    rng = random.Random(seed)
    price = 100.0
    bars: list[Bar] = []
    for i in range(n):
        price = max(1.0, price + math.sin(i / 10.0) * 0.5 + rng.uniform(-0.3, 0.3))
        close = price + rng.uniform(-0.2, 0.2)
        high = max(price, close) + rng.uniform(0.0, 0.3)
        low = min(price, close) - rng.uniform(0.0, 0.3)
        vol = rng.uniform(1.0, 10.0)
        bars.append(
            Bar(
                symbol="BTC/USDT",
                timeframe="1m",
                ts=T0 + timedelta(minutes=i),
                open=Decimal(str(round(price, 2))),
                high=Decimal(str(round(high, 2))),
                low=Decimal(str(round(low, 2))),
                close=Decimal(str(round(close, 2))),
                volume=Decimal(str(round(vol, 4))),
            )
        )
    return bars


@pytest.mark.fast
def test_feature_pipeline_is_deterministic() -> None:
    bars = make_bars()
    first = feature_rows("BTC/USDT", "1m", bars)
    second = feature_rows("BTC/USDT", "1m", bars)
    assert first == second
    assert len(first) > 0


@pytest.mark.fast
def test_features_have_expected_keys_after_warmup() -> None:
    rows = feature_rows("BTC/USDT", "1m", make_bars())
    last = rows[-1].values
    for key in ("log_ret_1", "rsi_14", "macd", "bb_pctb_20", "rel_vol_20", "trend_strength"):
        assert key in last, key
    # Calendar features are always present (no warmup).
    assert "hour_of_day" in last
    assert "day_of_week" in last


@pytest.mark.fast
def test_log_return_matches_manual_computation() -> None:
    bars = make_bars(n=50)
    df = bars_to_frame(bars)
    feats = compute_features(df)
    expected = math.log(float(bars[10].close) / float(bars[9].close))
    assert feats["log_ret_1"].iloc[10] == pytest.approx(expected, rel=1e-9)


@pytest.mark.fast
def test_rsi_saturates_on_monotonic_series() -> None:
    import pandas as pd

    close = pd.Series([float(i) for i in range(1, 40)])
    # All gains, no losses => RSI pinned at 100.
    assert rsi(close, 14).iloc[-1] == pytest.approx(100.0)


@pytest.mark.fast
def test_orderbook_features() -> None:
    snap = OrderBookSnapshot(
        symbol="BTC/USDT",
        ts=T0,
        bids=[(Decimal("100.0"), Decimal("3.0"))],
        asks=[(Decimal("100.2"), Decimal("1.0"))],
    )
    # spread = (100.2-100.0)/100.1 * 1e4 ~= 19.98 bps
    assert spread_bps(snap) == pytest.approx(19.98, abs=0.1)
    # imbalance = (3-1)/(3+1) = 0.5
    assert imbalance(snap) == pytest.approx(0.5)
    feats = orderbook_features(snap)
    assert feats["ob_imbalance"] == pytest.approx(0.5)
