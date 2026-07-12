"""Macro indicators via FRED (Section 8.4 — optional).

FRED is optional in v1: if ``FRED_API_KEY`` is unset or the call fails, this
returns an empty dict and the pipeline proceeds on cross-asset features alone.
Wire real series here (e.g. DFF, T10Y2Y) when the key is configured.
"""

from __future__ import annotations

import os

from src.common.logging import get_logger

log = get_logger("ingestion.macro")

# FRED series to pull when a key is configured. Extend as needed.
FRED_SERIES: dict[str, str] = {
    "fed_funds_rate": "DFF",
    "yield_curve_10y2y": "T10Y2Y",
}


def macro_snapshot() -> dict[str, float]:
    """Latest macro indicator values, or empty dict when unavailable."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return {}
    try:
        from fredapi import Fred

        fred = Fred(api_key=api_key)
        out: dict[str, float] = {}
        for name, series_id in FRED_SERIES.items():
            series = fred.get_series(series_id).dropna()
            if len(series):
                out[name] = float(series.iloc[-1])
        return out
    except Exception:
        log.warning("macro_fetch_failed")
        return {}
