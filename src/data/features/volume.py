"""Volume-derived features (Section 15.1)."""

from __future__ import annotations

import pandas as pd


def volume_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    vol = df["volume"]

    # Relative volume vs the 20-period average.
    out["rel_vol_20"] = vol / vol.rolling(20).mean()

    # Dollar (quote-currency) volume.
    out["dollar_vol"] = vol * df["close"]

    # Rolling VWAP deviation (typical-price VWAP over 20 bars).
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    num = (typical * vol).rolling(20).sum()
    den = vol.rolling(20).sum()
    vwap = num / den
    out["vwap_dev_20"] = (df["close"] - vwap) / vwap
    return out
