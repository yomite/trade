"""Tests for backfill segment computation (Section 10 Phase 1).

Locks the fix for the deep-backfill bug: an initial full load must fill history
older than the earliest stored bar, not just resume from the latest.
"""

from __future__ import annotations

import pytest
from src.data.ingestion.backfill import compute_segments

STEP = 10  # toy step in ms; the function is agnostic to the real value


@pytest.mark.fast
def test_empty_db_returns_full_range() -> None:
    assert compute_segments(None, None, 0, 100, 200, STEP) == [(100, 200)]


@pytest.mark.fast
def test_empty_range_returns_nothing() -> None:
    assert compute_segments(None, None, 0, 200, 200, STEP) == []


@pytest.mark.fast
def test_fills_both_deep_and_recent() -> None:
    # data covers [1000, 2000]; want [500, 3000) => deep + recent, middle skipped.
    segs = compute_segments(1000, 2000, 10, 500, 3000, STEP)
    assert segs == [(500, 1000), (2010, 3000)]


@pytest.mark.fast
def test_only_deep_history_missing() -> None:
    segs = compute_segments(1000, 2000, 10, 500, 2000, STEP)
    assert segs == [(500, 1000)]


@pytest.mark.fast
def test_only_recent_missing() -> None:
    segs = compute_segments(1000, 2000, 10, 1000, 3000, STEP)
    assert segs == [(2010, 3000)]


@pytest.mark.fast
def test_fully_covered_returns_nothing() -> None:
    assert compute_segments(1000, 2000, 10, 1000, 2005, STEP) == []
