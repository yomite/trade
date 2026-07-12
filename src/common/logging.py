"""Structured logging setup (Section 21.3).

All logs are structured JSON via structlog. Every entry carries a timestamp,
level, and logger name; call sites add action + context as keyword arguments.
Never log secrets or PII (Section 21.3).
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog
from structlog.stdlib import BoundLogger

_configured = False


def configure_logging(level: str = "INFO", json_format: bool = True) -> None:
    """Configure structlog + stdlib logging once, process-wide.

    Args:
        level: Minimum level name (e.g. ``"INFO"``, ``"DEBUG"``).
        json_format: JSON renderer for production; console renderer for local dev.
    """
    global _configured

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=numeric_level)

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_format else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str | None = None) -> BoundLogger:
    """Return a bound structured logger. Configures with defaults if needed."""
    if not _configured:
        configure_logging()
    return cast(BoundLogger, structlog.get_logger(name))
