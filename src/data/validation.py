"""Data-quality validation for the ingestion layer (Section 10 Phase 1).

Pure functions over bar sequences — no I/O, so they are deterministic and cheap
to unit-test. Detects:

- **OHLC inconsistency** (high < low, close outside [low, high], negatives)
- **Gaps** (missing bars between consecutive timestamps)
- **Duplicates** (repeated timestamps)
- **Staleness** (latest bar older than the freshness threshold — Section 4.3)

Ingestion raises/halts on structural problems (fail loud, Section 2.5); gaps are
reported and logged, not silently filled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from src.common.time import timeframe_seconds
from src.common.types import Bar


@dataclass(frozen=True, slots=True)
class Gap:
    """A run of missing bars between two present bars."""

    after: datetime  # last present bar before the gap
    before: datetime  # first present bar after the gap
    missing: int  # number of absent bars in between


def validate_ohlc(bar: Bar) -> list[str]:
    """Return a list of consistency problems for one bar (empty == valid)."""
    problems: list[str] = []
    if bar.high < bar.low:
        problems.append("high < low")
    if not (bar.low <= bar.open <= bar.high):
        problems.append("open outside [low, high]")
    if not (bar.low <= bar.close <= bar.high):
        problems.append("close outside [low, high]")
    if min(bar.open, bar.high, bar.low, bar.close) <= Decimal(0):
        problems.append("non-positive price")
    if bar.volume < Decimal(0):
        problems.append("negative volume")
    return problems


def find_duplicates(bars: list[Bar]) -> list[datetime]:
    """Return timestamps that appear more than once (ascending input assumed)."""
    seen: set[datetime] = set()
    dupes: list[datetime] = []
    for bar in bars:
        if bar.ts in seen:
            dupes.append(bar.ts)
        seen.add(bar.ts)
    return dupes


def detect_gaps(bars: list[Bar], timeframe: str) -> list[Gap]:
    """Find missing-bar runs in an ascending-ts bar list."""
    step = timedelta(seconds=timeframe_seconds(timeframe))
    gaps: list[Gap] = []
    for prev, cur in pairwise(bars):
        delta = cur.ts - prev.ts
        if delta > step:
            missing = round(delta / step) - 1
            if missing > 0:
                gaps.append(Gap(after=prev.ts, before=cur.ts, missing=missing))
    return gaps


def expected_bar_count(start: datetime, end: datetime, timeframe: str) -> int:
    """Number of bars expected in [start, end] inclusive of both ends."""
    step = timeframe_seconds(timeframe)
    span = int((end - start).total_seconds())
    return max(span // step + 1, 0)


def gap_rate(bars: list[Bar], timeframe: str) -> float:
    """Fraction of bars missing across the span the bars actually cover.

    0.0 means contiguous; the Phase 1 DoD requires < 0.001 (< 0.1%).
    """
    if len(bars) < 2:
        return 0.0
    expected = expected_bar_count(bars[0].ts, bars[-1].ts, timeframe)
    if expected <= 0:
        return 0.0
    missing = expected - len(bars)
    return max(missing, 0) / expected


def is_stale(latest_ts: datetime, now: datetime, max_age_seconds: int) -> bool:
    """True if the newest bar is older than the freshness threshold (Section 4.3)."""
    return (now - latest_ts).total_seconds() > max_age_seconds
