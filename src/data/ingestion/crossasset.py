"""Cross-asset regime data via yfinance (Section 15.1 cross-asset features).

Fetches VIX, DXY, S&P 500, and gold and derives the macro-context features that
capture "what kind of environment is this" without parsing news (Section 8.5).
These update slowly (hourly/daily) and are attached to bar features in the live
loop; they are NOT part of the deterministic per-bar transform.

Failure behavior (Section 8.4): on any fetch error, the last successful values
are returned from cache rather than crashing the pipeline.
"""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from src.common.logging import get_logger

log = get_logger("ingestion.crossasset")

# Logical name -> yfinance ticker (Section 15.1 table).
TICKERS: dict[str, str] = {
    "vix": "^VIX",
    "dxy": "DX-Y.NYB",
    "sp500": "^GSPC",
    "gold": "GC=F",
}

CloseFetcher = Callable[[dict[str, str]], dict[str, pd.Series]]


def compute_cross_asset_features(closes: dict[str, pd.Series]) -> dict[str, float]:
    """Derive the cross-asset feature dict from close-price series.

    Pure and testable — no network. Missing series are skipped.
    """
    out: dict[str, float] = {}

    if (vix := _clean(closes.get("vix"))) is not None and len(vix) >= 2:
        out["vix_level"] = float(vix.iloc[-1])
        out["vix_chg_1d"] = float(vix.iloc[-1] - vix.iloc[-2])

    if (dxy := _clean(closes.get("dxy"))) is not None and len(dxy) >= 6:
        out["dxy_level"] = float(dxy.iloc[-1])
        out["dxy_trend_5d"] = float(dxy.iloc[-1] / dxy.iloc[-6] - 1.0)

    if (sp := _clean(closes.get("sp500"))) is not None and len(sp) >= 21:
        rets = sp.pct_change()
        out["sp_ret_1d"] = float(rets.iloc[-1])
        out["sp_vol_20d"] = float(rets.tail(20).std())

    if (gold := _clean(closes.get("gold"))) is not None and len(gold) >= 2:
        out["gold_ret_1d"] = float(gold.pct_change().iloc[-1])

    return out


def _clean(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    cleaned = series.dropna()
    return cleaned if len(cleaned) else None


def _yf_download(tickers: dict[str, str]) -> dict[str, pd.Series]:
    import yfinance as yf

    frame = yf.download(
        list(tickers.values()), period="40d", interval="1d", progress=False, auto_adjust=True
    )
    close = frame["Close"]
    return {name: close[sym] for name, sym in tickers.items() if sym in close.columns}


class CrossAssetFeed:
    """Fetches and caches cross-asset regime features."""

    def __init__(self, fetcher: CloseFetcher | None = None) -> None:
        self._fetch = fetcher or _yf_download
        self._cache: dict[str, float] = {}

    def snapshot(self) -> dict[str, float]:
        """Current cross-asset features; returns cached values on fetch failure."""
        try:
            features = compute_cross_asset_features(self._fetch(TICKERS))
        except Exception:
            log.warning("crossasset_fetch_failed", using_cache=bool(self._cache))
            return dict(self._cache)
        self._cache = features
        return features
