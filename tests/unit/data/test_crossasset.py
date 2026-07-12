"""Tests for cross-asset feature computation (offline, stubbed fetcher)."""

from __future__ import annotations

import pandas as pd
import pytest
from src.data.ingestion.crossasset import CrossAssetFeed, compute_cross_asset_features


@pytest.mark.fast
def test_compute_cross_asset_features() -> None:
    closes = {
        "vix": pd.Series([14.0, 15.0]),
        "dxy": pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0]),
        "sp500": pd.Series([100.0 + i for i in range(25)]),
        "gold": pd.Series([2000.0, 2010.0]),
    }
    feats = compute_cross_asset_features(closes)
    assert feats["vix_level"] == 15.0
    assert feats["vix_chg_1d"] == pytest.approx(1.0)
    assert feats["dxy_trend_5d"] == pytest.approx(0.05)
    assert "sp_ret_1d" in feats
    assert "sp_vol_20d" in feats
    assert feats["gold_ret_1d"] == pytest.approx(0.005, rel=1e-6)


@pytest.mark.fast
def test_feed_caches_and_survives_failure() -> None:
    feed = CrossAssetFeed(fetcher=lambda _: {"vix": pd.Series([10.0, 11.0])})
    first = feed.snapshot()
    assert first["vix_level"] == 11.0

    def boom(_: dict[str, str]) -> dict[str, pd.Series]:
        raise RuntimeError("network down")

    feed._fetch = boom  # simulate outage
    assert feed.snapshot() == first  # falls back to cache, no crash


@pytest.mark.fast
def test_feed_empty_cache_on_first_failure() -> None:
    def boom(_: dict[str, str]) -> dict[str, pd.Series]:
        raise RuntimeError("down")

    assert CrossAssetFeed(fetcher=boom).snapshot() == {}
