"""Run the Bybit live websocket feed until interrupted (Phase 1 24h soak).

Usage:
    python scripts/run_live_feed.py            # feed the configured universe

Writes confirmed 1m bars, trades, and order-book snapshots to TimescaleDB.
Stop with Ctrl+C (SIGINT) or SIGTERM; trades are flushed on shutdown.
"""

from __future__ import annotations

import signal
import threading
from types import FrameType

from src.common.config import load_config
from src.common.env import load_env
from src.common.logging import configure_logging, get_logger
from src.data.ingestion.bybit_ws import BybitWebsocketFeed


def main() -> int:
    load_env()
    configure_logging(json_format=False)
    log = get_logger("run_live_feed")

    cfg = load_config(mode="paper")
    feed = BybitWebsocketFeed(list(cfg.universe.symbols))

    stop = threading.Event()

    def _handle(_signum: int, _frame: FrameType | None) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    feed.start()
    log.info("live_feed_running", detail="Ctrl+C to stop")
    try:
        stop.wait()
    finally:
        feed.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
