"""HARD CONSTRAINTS — the non-negotiable risk and safety rules (Section 4).

These are enforced in code and cannot be bypassed by any strategy, model, or
runtime configuration override. Changing any value here is a deliberate act:
edit this file, update CLAUDE.md Section 4, and commit with explicit
justification (Section 4 preamble).

Money and percentage limits are ``Decimal`` to keep sizing math exact
(Section 21.4). Pure statistical thresholds (Sharpe, sigma, accuracy) are
``float`` because they are compared against float-valued metrics.

The config layer (``src/common/config.py``) MIRRORS some of these for
visibility but validates that runtime config is never *looser* than the values
here — the constants always win.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from src.common.types import BreakerRecovery, BreakerType

# --- 4.1 Capital and position limits ----------------------------------------
RISK_PER_TRADE_PCT: Final = Decimal("1.0")  # % of account equity per trade
MAX_POSITION_PCT: Final = Decimal("25.0")  # % of equity in one position
MAX_CONCURRENT_POSITIONS: Final = 3
MAX_LEVERAGE: Final = Decimal("1.0")  # spot only, no margin
KELLY_FRACTION_CAP: Final = Decimal("0.25")  # quarter Kelly
MIN_TRADE_NOTIONAL_USD: Final = Decimal("10")  # minimum trade size

# --- 4.2 Drawdown circuit breakers ------------------------------------------
DAILY_LOSS_PAUSE_PCT: Final = Decimal("3.0")  # pause new trades 24h, auto-resume
WEEKLY_LOSS_PAUSE_PCT: Final = Decimal("8.0")  # pause all 7d, manual restart
TOTAL_DRAWDOWN_SHUTDOWN_PCT: Final = Decimal("15.0")  # full shutdown, manual review
CONSEC_LOSSES_SUSPEND: Final = 5  # per-strategy suspension threshold

# --- 4.3 Data and model safety ----------------------------------------------
STALE_BAR_SECONDS: Final = 60  # 1m bar staleness → halt
MODEL_OUTPUT_MIN: Final = Decimal("-1")  # valid model output range
MODEL_OUTPUT_MAX: Final = Decimal("1")
SLIPPAGE_SUSPEND_MULTIPLE: Final = Decimal("3.0")  # real > 3x expected → suspend
MIN_MODEL_CONFIDENCE: Final = Decimal("0.60")  # below → filter out signal
MIN_BACKTEST_SHARPE: Final = 1.0  # OOS deploy gate (Section 15.2)
MAX_BACKTEST_DRAWDOWN_PCT: Final = 20.0  # deploy gate (Section 15.2)
MIN_HIT_RATE: Final = 0.50  # directional deploy gate
LIVE_DRIFT_PAUSE_SIGMA: Final = 2.0  # >2 sigma from backtest -> auto-pause
LIVE_DRIFT_SUSPEND_SIGMA: Final = 3.0  # >3 sigma -> auto-suspend (Section 17.2)

# --- 4.4 Operational --------------------------------------------------------
WARMUP_SECONDS: Final = 300  # no trading in first 5 minutes
MAX_CLOCK_DRIFT_SECONDS: Final = 1.0  # halt if drift exceeds this
API_KEY_MUST_BE_TRADE_ONLY: Final = True  # withdraw permission forbidden

# --- Cost-vs-edge gate (Section 18, Stage 9) --------------------------------
COST_EDGE_MULTIPLE: Final = Decimal("1.2")  # required edge/cost ratio

# --- Execution safety (Section 16.2) ----------------------------------------
STOP_REGISTRATION_TIMEOUT_S: Final = 3.0  # else close position defensively
RECONCILE_INTERVAL_S: Final = 60  # position reconciliation cadence

# --- Strategy lifecycle (Section 14.2) --------------------------------------
SHADOW_MIN_DAYS: Final = 14
SHADOW_MIN_SIGNALS: Final = 50
SHADOW_PROMOTE_MIN_SHARPE: Final = 1.0
LIVE_SUSPEND_MAX_SHARPE_30D: Final = 0.0  # 30-day live Sharpe < 0 → suspend
EVOLVE_PROMOTE_SHARPE_MARGIN: Final = 0.3  # candidate must beat incumbent by this

# --- Exchange category lock (Section 16.4.4) --------------------------------
ALLOWED_EXCHANGE_CATEGORY: Final = "spot"  # linear/inverse/option rejected

# --- Circuit breaker action table (Section 4.2) -----------------------------
# Maps each drawdown breaker to its recovery discipline. The risk engine uses
# this to decide whether a trip auto-resumes or blocks until a human acts.
BREAKER_RECOVERY: Final[dict[BreakerType, BreakerRecovery]] = {
    BreakerType.DAILY_LOSS: BreakerRecovery.AUTO_RESUME,
    BreakerType.WEEKLY_LOSS: BreakerRecovery.MANUAL_RESTART,
    BreakerType.TOTAL_DRAWDOWN: BreakerRecovery.MANUAL_REVIEW,
    BreakerType.CONSEC_LOSSES: BreakerRecovery.AUTO_AFTER_RETRAIN,
}
