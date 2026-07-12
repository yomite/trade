"""Compute and store features for stored bars (Section 15.1; Phase 1 DoD).

Reads bars from TimescaleDB, runs the deterministic feature pipeline, and
upserts versioned feature rows into the ``features`` table.

Usage:
    python scripts/compute_features.py                      # universe, 1m
    python scripts/compute_features.py --symbols BTC/USDT --timeframe 1m
"""

from __future__ import annotations

import argparse

from src.common.config import load_config
from src.common.env import load_env
from src.common.logging import configure_logging, get_logger
from src.data.features.pipeline import FEATURE_SET_VERSION, feature_rows
from src.data.storage.timescale import Database

log = get_logger("compute_features")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compute and store bar features")
    p.add_argument("--mode", default="paper")
    p.add_argument("--symbols", default=None, help="comma-separated; default = universe")
    p.add_argument("--timeframe", default="1m")
    return p.parse_args()


def main() -> int:
    load_env()
    configure_logging(json_format=False)
    args = _parse_args()

    cfg = load_config(mode=args.mode)
    symbols = args.symbols.split(",") if args.symbols else list(cfg.universe.symbols)

    db = Database()
    db.apply_schema()
    for symbol in symbols:
        bars = db.fetch_bars(symbol, args.timeframe)
        rows = feature_rows(symbol, args.timeframe, bars, FEATURE_SET_VERSION)
        written = 0
        # Upsert in chunks to bound memory / statement size on long histories.
        for i in range(0, len(rows), 5000):
            written += db.upsert_features(rows[i : i + 5000])
        log.info(
            "features_stored",
            symbol=symbol,
            timeframe=args.timeframe,
            bars=len(bars),
            feature_rows=written,
            feature_set=FEATURE_SET_VERSION,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
