"""Own-asset regime features (Section 15.1).

Deterministic trend-strength and volatility-regime descriptors. The HMM-based
regime *classifier* is a separate model built in Phase 4 (Section 15); these are
the cheap, always-available features that feed it and the strategies.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.data.features.indicators import adx

_INF = float("inf")


def regime_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    close = df["close"]

    # Trend strength (ADX) and normalized trend direction (SMA slope).
    out["trend_strength"] = adx(df, 14)
    sma50 = close.rolling(50).mean()
    out["sma50_slope"] = sma50.diff(10) / sma50

    # Volatility regime: z-score of realized vol vs its rolling distribution,
    # bucketed low(0) / normal(1) / elevated(2) / extreme(3).
    r1 = np.log(close).diff(1)
    rv = r1.rolling(30).std()
    rv_mean = rv.rolling(200, min_periods=50).mean()
    rv_std = rv.rolling(200, min_periods=50).std()
    vol_z = (rv - rv_mean) / rv_std
    out["vol_z"] = vol_z
    out["vol_regime"] = pd.cut(
        vol_z, bins=[-_INF, -0.5, 0.5, 1.5, _INF], labels=[0, 1, 2, 3]
    ).astype(float)
    return out
