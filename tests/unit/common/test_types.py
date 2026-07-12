"""Tests for shared enums (Section 11, 12, 19)."""

from __future__ import annotations

import pytest
from src.common.types import AlertLevel, Mode, OrderType, Timeframe


@pytest.mark.fast
def test_str_enums_have_expected_wire_values() -> None:
    assert Mode.PAPER.value == "paper"
    assert Timeframe.M1.value == "1m"
    assert Timeframe.H1.value == "1h"
    assert OrderType.LIMIT.value == "limit"
    # StrEnum members compare equal to their string value.
    assert Mode.LIVE == "live"


@pytest.mark.fast
def test_alert_levels_are_ordered() -> None:
    assert AlertLevel.INFO < AlertLevel.WARNING < AlertLevel.ERROR < AlertLevel.CRITICAL
