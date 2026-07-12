"""Time utilities — always UTC (Section 21.4).

All code reads the current time via :func:`now` rather than
``datetime.now()`` directly, so the backtester can substitute a deterministic
clock and replay history exactly (Section 13.1). Never use naive datetimes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime


def _default_clock() -> datetime:
    return datetime.now(UTC)


_clock: Callable[[], datetime] = _default_clock


def now() -> datetime:
    """Current time as a timezone-aware UTC datetime.

    Reads through the injectable clock so tests and backtests can control it.
    """
    return _clock()


def set_clock(clock: Callable[[], datetime]) -> None:
    """Override the clock (backtest replay, tests). Use :func:`reset_clock` after."""
    global _clock
    _clock = clock


def reset_clock() -> None:
    """Restore the real wall-clock."""
    global _clock
    _clock = _default_clock


def to_ms(dt: datetime) -> int:
    """UTC datetime → Unix epoch milliseconds (Bybit's timestamp unit)."""
    if dt.tzinfo is None:
        raise ValueError("refusing to convert a naive datetime; all times must be UTC-aware")
    return int(dt.timestamp() * 1000)


def from_ms(ms: int) -> datetime:
    """Unix epoch milliseconds → timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


_TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


def timeframe_seconds(timeframe: str) -> int:
    """Width of a bar timeframe in seconds (e.g. '1m' → 60)."""
    try:
        return _TIMEFRAME_SECONDS[timeframe]
    except KeyError:
        raise ValueError(f"unknown timeframe {timeframe!r}") from None
