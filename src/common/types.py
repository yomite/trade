"""Shared types used across all layers.

Kept dependency-free (imports nothing from the rest of ``src``) so it can be
imported anywhere without creating cycles. Money and quantity values use
``Decimal`` — never ``float`` — because float arithmetic loses cents
(Section 11, Section 21.4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import IntEnum, StrEnum

# Type aliases for readability at call sites.
Symbol = str
Money = Decimal


class Mode(StrEnum):
    """Runtime mode (Section 12)."""

    PAPER = "paper"
    LIVE = "live"
    BACKTEST = "backtest"


class Timeframe(StrEnum):
    """Candle timeframes in scope for v1 (Section 5.1)."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"


class Direction(StrEnum):
    """Signal direction."""

    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class Side(StrEnum):
    """Order side."""

    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    """Order types (Section 16.1)."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(StrEnum):
    """Lifecycle of an order on the exchange."""

    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ExitReason(StrEnum):
    """Why a position was closed (Section 11.2 trades.exit_reason, Section 18.11)."""

    STOP = "stop"
    TARGET = "target"
    SIGNAL = "signal"
    TIME = "time"
    REGIME = "regime"
    TRAILING = "trailing"
    MANUAL = "manual"
    CIRCUIT_BREAKER = "circuit_breaker"


class BreakerType(StrEnum):
    """Circuit breaker categories (Section 4.2, 4.3)."""

    DAILY_LOSS = "daily_loss"
    WEEKLY_LOSS = "weekly_loss"
    TOTAL_DRAWDOWN = "total_drawdown"
    CONSEC_LOSSES = "consec_losses"
    STALE_DATA = "stale_data"
    ORDERBOOK_MISSING = "orderbook_missing"
    SLIPPAGE = "slippage"
    CLOCK_DRIFT = "clock_drift"
    EXCHANGE_DISCONNECT = "exchange_disconnect"
    RECONCILIATION = "reconciliation"
    MODEL_OUTPUT = "model_output"


class BreakerRecovery(StrEnum):
    """How a tripped breaker is cleared (Section 4.2)."""

    AUTO_RESUME = "auto_resume"
    AUTO_AFTER_RETRAIN = "auto_after_retrain"
    MANUAL_RESTART = "manual_restart"
    MANUAL_REVIEW = "manual_review"


class StrategyStatus(StrEnum):
    """Strategy lifecycle states (Section 14.2)."""

    SHADOW = "shadow"
    LIVE = "live"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class ModelStatus(StrEnum):
    """Model registry states (Section 15.2)."""

    TRAINED = "trained"
    VALIDATED = "validated"
    DEPLOYED = "deployed"
    RETIRED = "retired"


class AlertLevel(IntEnum):
    """Notification severity (Section 19.2.3). Ordered so filtering by
    threshold is a simple comparison."""

    INFO = 10
    WARNING = 20
    ERROR = 30
    CRITICAL = 40


# --- Data-layer row models (mirror the Section 11 tables) --------------------
# Prices/quantities are Decimal; timestamps are UTC-aware datetimes. These are
# the in-memory representation written to / read from TimescaleDB.


@dataclass(frozen=True, slots=True)
class Bar:
    """One OHLCV candle (table ``bars``)."""

    symbol: Symbol
    timeframe: str
    ts: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int | None = None


@dataclass(frozen=True, slots=True)
class Trade:
    """One tick-level trade (table ``trades_raw``)."""

    symbol: Symbol
    ts: datetime
    price: Decimal
    size: Decimal
    side: Side
    trade_id: str


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    """Top-N order book snapshot (table ``orderbook_snapshots``)."""

    symbol: Symbol
    ts: datetime
    bids: list[tuple[Decimal, Decimal]]  # [(price, size), ...] best-first
    asks: list[tuple[Decimal, Decimal]]


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """A computed feature vector at one timestamp (table ``features``)."""

    symbol: Symbol
    timeframe: str
    ts: datetime
    feature_set: str
    values: dict[str, float] = field(default_factory=dict)
