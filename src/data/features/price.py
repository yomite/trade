"""Price-derived features (Section 15.1).

Stationary transforms only — raw prices are never used directly as features
(Section 15.1). Log returns, realized volatility, ATR-normalized range, distance
from rolling extremes, and volatility-of-volatility.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.features.indicators import atr

RETURN_HORIZONS: tuple[int, ...] = (1, 5, 15, 60)
VOL_WINDOWS: tuple[int, ...] = (14, 30)


def price_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    close = df["close"]
    log_close = np.log(close)

    # Log returns at multiple horizons.
    for h in RETURN_HORIZONS:
        out[f"log_ret_{h}"] = log_close.diff(h)

    # Realized volatility = rolling std of 1-bar log returns.
    r1 = log_close.diff(1)
    for w in VOL_WINDOWS:
        out[f"rv_{w}"] = r1.rolling(w).std()

    # ATR and range/ATR ratio.
    atr14 = atr(df, 14)
    out["atr_14"] = atr14
    out["range_atr"] = (df["high"] - df["low"]) / atr14

    # Distance from rolling 20-period high/low as a fraction.
    hi20 = df["high"].rolling(20).max()
    lo20 = df["low"].rolling(20).min()
    out["dist_high_20"] = (close - hi20) / hi20
    out["dist_low_20"] = (close - lo20) / lo20

    # Volatility of volatility.
    out["vov_14"] = out["rv_14"].rolling(14).std()
    return out
