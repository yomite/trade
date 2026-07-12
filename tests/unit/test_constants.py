"""Verify HARD CONSTRAINTS match CLAUDE.md Section 4 exactly.

If a value here is changed without updating Section 4, this test is the tripwire.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from src import constants
from src.common.types import BreakerRecovery, BreakerType


@pytest.mark.fast
def test_capital_and_position_limits() -> None:
    # Section 4.1
    assert constants.RISK_PER_TRADE_PCT == Decimal("1.0")
    assert constants.MAX_POSITION_PCT == Decimal("25.0")
    assert constants.MAX_CONCURRENT_POSITIONS == 3
    assert constants.MAX_LEVERAGE == Decimal("1.0")
    assert constants.KELLY_FRACTION_CAP == Decimal("0.25")
    assert constants.MIN_TRADE_NOTIONAL_USD == Decimal("10")


@pytest.mark.fast
def test_drawdown_circuit_breakers() -> None:
    # Section 4.2
    assert constants.DAILY_LOSS_PAUSE_PCT == Decimal("3.0")
    assert constants.WEEKLY_LOSS_PAUSE_PCT == Decimal("8.0")
    assert constants.TOTAL_DRAWDOWN_SHUTDOWN_PCT == Decimal("15.0")
    assert constants.CONSEC_LOSSES_SUSPEND == 5


@pytest.mark.fast
def test_data_and_model_safety() -> None:
    # Section 4.3
    assert constants.STALE_BAR_SECONDS == 60
    assert constants.MODEL_OUTPUT_MIN == Decimal("-1")
    assert constants.MODEL_OUTPUT_MAX == Decimal("1")
    assert constants.SLIPPAGE_SUSPEND_MULTIPLE == Decimal("3.0")
    assert constants.MIN_MODEL_CONFIDENCE == Decimal("0.60")
    assert constants.MIN_BACKTEST_SHARPE == 1.0


@pytest.mark.fast
def test_operational_constraints() -> None:
    # Section 4.4
    assert constants.WARMUP_SECONDS == 300
    assert constants.MAX_CLOCK_DRIFT_SECONDS == 1.0
    assert constants.API_KEY_MUST_BE_TRADE_ONLY is True


@pytest.mark.fast
def test_spot_only_category() -> None:
    # Section 16.4.4
    assert constants.ALLOWED_EXCHANGE_CATEGORY == "spot"


@pytest.mark.fast
def test_breaker_recovery_table() -> None:
    # Section 4.2 recovery disciplines
    assert constants.BREAKER_RECOVERY[BreakerType.DAILY_LOSS] == BreakerRecovery.AUTO_RESUME
    assert constants.BREAKER_RECOVERY[BreakerType.WEEKLY_LOSS] == BreakerRecovery.MANUAL_RESTART
    assert constants.BREAKER_RECOVERY[BreakerType.TOTAL_DRAWDOWN] == BreakerRecovery.MANUAL_REVIEW
    assert (
        constants.BREAKER_RECOVERY[BreakerType.CONSEC_LOSSES] == BreakerRecovery.AUTO_AFTER_RETRAIN
    )


@pytest.mark.fast
def test_money_limits_are_decimal_not_float() -> None:
    # Section 21.4: money/percentage limits must be Decimal, never float.
    for name in (
        "RISK_PER_TRADE_PCT",
        "MAX_POSITION_PCT",
        "KELLY_FRACTION_CAP",
        "MIN_TRADE_NOTIONAL_USD",
        "DAILY_LOSS_PAUSE_PCT",
        "COST_EDGE_MULTIPLE",
    ):
        assert isinstance(getattr(constants, name), Decimal), name
