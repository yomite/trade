"""Feature pipeline — bars in, versioned feature rows out (Section 15.1).

Deterministic end-to-end: identical bars always produce identical feature rows
(Phase 1 DoD). Feature sets are versioned (``feature_set``) so a model trained on
one version always reads that version (Section 15.1).
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from src.common.types import Bar, FeatureRow
from src.data.features.calendar import calendar_features
from src.data.features.indicators import indicator_features
from src.data.features.price import price_features
from src.data.features.regime import regime_features
from src.data.features.volume import volume_features

FEATURE_SET_VERSION = "v1"

_COLUMNS = ("open", "high", "low", "close", "volume")


def bars_to_frame(bars: list[Bar]) -> pd.DataFrame:
    """List[Bar] -> float OHLCV DataFrame indexed by ts (ascending)."""
    index = pd.DatetimeIndex([b.ts for b in bars], name="ts")
    frame = pd.DataFrame(
        {
            "open": [float(b.open) for b in bars],
            "high": [float(b.high) for b in bars],
            "low": [float(b.low) for b in bars],
            "close": [float(b.close) for b in bars],
            "volume": [float(b.volume) for b in bars],
        },
        index=index,
        columns=list(_COLUMNS),
    )
    return frame.sort_index()


def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Concatenate all feature blocks into one frame aligned to ``df.index``."""
    blocks = [
        price_features(df),
        volume_features(df),
        indicator_features(df),
        regime_features(df),
        calendar_features(df.index),
    ]
    return pd.concat(blocks, axis=1)


def iter_feature_rows(
    symbol: str,
    timeframe: str,
    bars: list[Bar],
    feature_set: str = FEATURE_SET_VERSION,
    chunk_size: int = 20_000,
) -> Iterator[list[FeatureRow]]:
    """Yield feature rows in chunks so full-history runs don't hold millions of
    FeatureRow objects in memory at once.

    NaN feature values (warmup periods) are dropped per row; rows with no valid
    features are omitted entirely.
    """
    if not bars:
        return
    feats = compute_features(bars_to_frame(bars))
    buffer: list[FeatureRow] = []
    for ts, series in feats.iterrows():
        values = {name: float(v) for name, v in series.items() if pd.notna(v)}
        if values:
            buffer.append(FeatureRow(symbol, timeframe, ts.to_pydatetime(), feature_set, values))
        if len(buffer) >= chunk_size:
            yield buffer
            buffer = []
    if buffer:
        yield buffer


def feature_rows(
    symbol: str,
    timeframe: str,
    bars: list[Bar],
    feature_set: str = FEATURE_SET_VERSION,
) -> list[FeatureRow]:
    """Compute all feature rows for a bar series (convenience wrapper)."""
    rows: list[FeatureRow] = []
    for chunk in iter_feature_rows(symbol, timeframe, bars, feature_set):
        rows.extend(chunk)
    return rows
