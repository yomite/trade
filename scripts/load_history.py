"""Bulk historical loader — backfills OHLCV bars into TimescaleDB (Section 10 Phase 1).

Resumable: for each symbol/timeframe it starts from the bar after the newest one
already stored (or `--years` back if empty), so re-running fills only what's
missing. Idempotent writes mean an interrupted run can simply be restarted.

Examples:
    python scripts/load_history.py                       # 5y of 1m for the universe
    python scripts/load_history.py --days 2              # quick recent slice (testing)
    python scripts/load_history.py --symbols BTC/USDT --timeframes 1m,1h
"""

from __future__ import annotations

import argparse
from datetime import timedelta

from src.common.config import load_config
from src.common.env import load_env
from src.common.logging import configure_logging, get_logger
from src.common.time import from_ms, now, timeframe_seconds, to_ms
from src.data.ingestion.bybit_rest import BybitREST, default_history_start_ms
from src.data.storage.timescale import Database
from src.data.validation import expected_bar_count

log = get_logger("load_history")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill historical bars into TimescaleDB")
    p.add_argument("--mode", default="paper", help="config mode for the universe defaults")
    p.add_argument("--symbols", default=None, help="comma-separated, e.g. BTC/USDT,ETH/USDT")
    p.add_argument("--timeframes", default="1m", help="comma-separated, e.g. 1m,1h")
    p.add_argument("--years", type=int, default=5, help="history depth when starting empty")
    p.add_argument("--days", type=int, default=None, help="override: only this many days back")
    return p.parse_args()


def _load_symbol(
    db: Database, client: BybitREST, symbol: str, timeframe: str, start_ms: int
) -> int:
    end_ms = to_ms(now())
    # Resume from just after the newest stored bar, if any.
    latest = db.latest_bar_ts(symbol, timeframe)
    if latest is not None:
        resume_ms = to_ms(latest) + timeframe_seconds(timeframe) * 1000
        start_ms = max(start_ms, resume_ms)
    if start_ms >= end_ms:
        log.info("already_current", symbol=symbol, timeframe=timeframe)
        return 0

    written = 0
    for batch in client.iter_klines_range(symbol, timeframe, start_ms, end_ms):
        written += db.upsert_bars(batch)
        log.info(
            "batch",
            symbol=symbol,
            timeframe=timeframe,
            up_to=batch[-1].ts.isoformat(),
            written=written,
        )
    return written


def _report(db: Database, symbol: str, timeframe: str) -> None:
    earliest, latest, count = db.bar_span(symbol, timeframe)
    if earliest is None or latest is None:
        log.warning("no_data", symbol=symbol, timeframe=timeframe)
        return
    expected = expected_bar_count(earliest, latest, timeframe)
    missing = max(expected - count, 0)
    rate = missing / expected if expected else 0.0
    log.info(
        "loaded",
        symbol=symbol,
        timeframe=timeframe,
        bars=count,
        span=f"{earliest.date()}..{latest.date()}",
        gap_rate=f"{rate:.4%}",
        dod_ok=rate < 0.001,  # Phase 1 DoD: < 0.1% gap rate
    )
    db.log_ingestion("bybit_rest", symbol, timeframe, earliest, latest, count, missing)


def main() -> int:
    load_env()
    configure_logging(json_format=False)

    args = _parse_args()
    cfg = load_config(mode=args.mode)
    symbols = args.symbols.split(",") if args.symbols else list(cfg.universe.symbols)
    timeframes = args.timeframes.split(",")

    if args.days is not None:
        start_ms = to_ms(now() - timedelta(days=args.days))
    else:
        start_ms = default_history_start_ms(args.years)
    log.info("start", symbols=symbols, timeframes=timeframes, since=from_ms(start_ms).isoformat())

    db = Database()
    db.apply_schema()
    with BybitREST() as client:
        for symbol in symbols:
            for timeframe in timeframes:
                _load_symbol(db, client, symbol, timeframe, start_ms)
                _report(db, symbol, timeframe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
