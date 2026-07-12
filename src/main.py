"""Entry point — wires the layers together (Section 9).

Phase 0 establishes configuration + logging wiring only. The live trading loop
is built up across later phases (data → risk → backtest → strategies →
execution). Running this now validates that config loads and logging works.
"""

from __future__ import annotations

import argparse
import sys

from src.common.config import Config, load_config
from src.common.logging import configure_logging, get_logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="tradingbot", description="Autonomous trading bot")
    parser.add_argument(
        "--mode",
        choices=["paper", "live", "backtest"],
        default=None,
        help="Runtime mode; overrides config and BOT_MODE.",
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directory containing base.yaml and {mode}.yaml.",
    )
    return parser.parse_args(argv)


def build_config(argv: list[str] | None = None) -> Config:
    args = parse_args(argv)
    return load_config(mode=args.mode, config_dir=args.config_dir)


def main(argv: list[str] | None = None) -> int:
    config = build_config(argv)
    configure_logging(level=config.logging.level, json_format=config.logging.format == "json")
    log = get_logger("main")
    log.info(
        "startup",
        mode=config.mode.value,
        symbols=config.universe.symbols,
        exchange=config.exchange.name,
        testnet=config.exchange.testnet,
    )
    # The trading loop is not implemented until Phase 5 (paper execution).
    log.warning(
        "trading_loop_not_implemented",
        detail="Phase 0 wiring only; no orders are placed. See IMPLEMENTATION_PLAN.md.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
