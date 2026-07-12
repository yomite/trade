"""Apply the TimescaleDB schema to the configured database (idempotent).

Usage:
    python scripts/init_db.py

Reads DATABASE_URL from .env. Safe to run repeatedly — every statement in
schema.sql uses IF NOT EXISTS.
"""

from __future__ import annotations

from src.common.env import load_env
from src.common.logging import configure_logging, get_logger
from src.data.storage.timescale import Database


def main() -> int:
    load_env()
    configure_logging(json_format=False)
    log = get_logger("init_db")

    db = Database()
    db.apply_schema()
    if not db.ping():
        log.error("timescaledb_missing", detail="timescaledb extension not found")
        return 1
    log.info(
        "db_ready",
        btc_1m_bars=db.count_bars("BTC/USDT", "1m"),
        eth_1m_bars=db.count_bars("ETH/USDT", "1m"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
