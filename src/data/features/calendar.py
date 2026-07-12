"""Calendar / known-schedule features (Section 15.1).

Derived purely from the bar timestamp, so fully deterministic. Clock features
(hour, weekday) and BTC halving-cycle position are implemented here. Economic
event proximity (FOMC / CPI / NFP) needs a maintained schedule table and is
wired in later — see ``ECONOMIC_EVENTS`` placeholder.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

# Known BTC halving dates (UTC). Extend as future halvings are scheduled.
_HALVINGS: tuple[datetime, ...] = (
    datetime(2012, 11, 28, tzinfo=UTC),
    datetime(2016, 7, 9, tzinfo=UTC),
    datetime(2020, 5, 11, tzinfo=UTC),
    datetime(2024, 4, 20, tzinfo=UTC),
    datetime(2028, 4, 17, tzinfo=UTC),  # projected
)

# Placeholder for scheduled macro events (Section 15.1). Populate with a
# maintained schedule to enable pre-event de-risking features.
ECONOMIC_EVENTS: dict[str, tuple[datetime, ...]] = {}


def _days_since_last_halving(ts: datetime) -> float:
    past = [h for h in _HALVINGS if h <= ts]
    return (ts - past[-1]).total_seconds() / 86400.0 if past else float("nan")


def _days_to_next_halving(ts: datetime) -> float:
    future = [h for h in _HALVINGS if h > ts]
    return (future[0] - ts).total_seconds() / 86400.0 if future else float("nan")


def calendar_features(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Clock + halving-cycle features for each timestamp in the index."""
    out = pd.DataFrame(index=index)
    out["hour_of_day"] = index.hour.astype(float)
    out["day_of_week"] = index.dayofweek.astype(float)
    out["is_weekend"] = (index.dayofweek >= 5).astype(float)
    out["days_since_halving"] = [_days_since_last_halving(ts.to_pydatetime()) for ts in index]
    out["days_to_halving"] = [_days_to_next_halving(ts.to_pydatetime()) for ts in index]
    return out
