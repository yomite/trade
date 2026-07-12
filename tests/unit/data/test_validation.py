"""Tests for data-quality validation (Section 10 Phase 1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from src.common.types import Bar
from src.data.validation import (
    detect_gaps,
    expected_bar_count,
    find_duplicates,
    gap_rate,
    is_stale,
    validate_ohlc,
)

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def _bar(minute: int, o: str = "100", h: str = "101", low: str = "99", c: str = "100.5") -> Bar:
    return Bar(
        symbol="BTC/USDT",
        timeframe="1m",
        ts=T0 + timedelta(minutes=minute),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal("1.0"),
    )


@pytest.mark.fast
def test_validate_ohlc_accepts_valid_bar() -> None:
    assert validate_ohlc(_bar(0)) == []


@pytest.mark.fast
def test_validate_ohlc_flags_high_below_low() -> None:
    problems = validate_ohlc(_bar(0, h="98"))
    assert "high < low" in problems


@pytest.mark.fast
def test_validate_ohlc_flags_close_outside_range_and_negative() -> None:
    assert "close outside [low, high]" in validate_ohlc(_bar(0, c="200"))
    assert "non-positive price" in validate_ohlc(_bar(0, o="0", low="0"))


@pytest.mark.fast
def test_no_gaps_when_contiguous() -> None:
    bars = [_bar(i) for i in range(10)]
    assert detect_gaps(bars, "1m") == []
    assert gap_rate(bars, "1m") == 0.0


@pytest.mark.fast
def test_detects_gap() -> None:
    bars = [_bar(0), _bar(1), _bar(5)]  # minutes 2,3,4 missing
    gaps = detect_gaps(bars, "1m")
    assert len(gaps) == 1
    assert gaps[0].missing == 3
    assert gaps[0].after == T0 + timedelta(minutes=1)
    assert gaps[0].before == T0 + timedelta(minutes=5)


@pytest.mark.fast
def test_find_duplicates() -> None:
    bars = [_bar(0), _bar(1), _bar(1), _bar(2)]
    assert find_duplicates(bars) == [T0 + timedelta(minutes=1)]


@pytest.mark.fast
def test_expected_bar_count_and_gap_rate() -> None:
    # 0..9 minutes present = 10 bars over a 9-minute span => 10 expected, 0 missing.
    bars = [_bar(i) for i in range(10)]
    assert expected_bar_count(bars[0].ts, bars[-1].ts, "1m") == 10
    # Drop one interior bar -> 1 of 10 missing = 10%.
    sparse = [b for b in bars if b.ts != T0 + timedelta(minutes=5)]
    assert gap_rate(sparse, "1m") == pytest.approx(0.1)


@pytest.mark.fast
def test_is_stale() -> None:
    now = T0 + timedelta(seconds=120)
    assert is_stale(T0, now, max_age_seconds=60) is True
    assert is_stale(T0 + timedelta(seconds=90), now, max_age_seconds=60) is False
