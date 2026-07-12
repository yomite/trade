"""Tests for the injectable UTC clock (Section 21.4)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from src.common import time as t


@pytest.mark.fast
def test_now_is_utc_aware() -> None:
    dt = t.now()
    assert dt.tzinfo is not None
    assert dt.utcoffset() == UTC.utcoffset(None)


@pytest.mark.fast
def test_set_and_reset_clock() -> None:
    fixed = datetime(2026, 5, 12, 14, 32, tzinfo=UTC)
    t.set_clock(lambda: fixed)
    try:
        assert t.now() == fixed
    finally:
        t.reset_clock()
    assert t.now() != fixed


@pytest.mark.fast
def test_ms_round_trip() -> None:
    dt = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert t.from_ms(t.to_ms(dt)) == dt


@pytest.mark.fast
def test_to_ms_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="naive"):
        t.to_ms(datetime(2026, 1, 1, 0, 0, 0))
