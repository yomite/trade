"""Smoke test for the entry-point wiring (Phase 0)."""

from __future__ import annotations

import pytest
from src.main import build_config, main


@pytest.mark.fast
def test_build_config_selects_mode() -> None:
    cfg = build_config(["--mode", "paper"])
    assert cfg.mode.value == "paper"
    assert cfg.exchange.name == "bybit"


@pytest.mark.fast
def test_main_runs_and_returns_zero() -> None:
    # Phase 0: config + logging wire up, no trading loop yet.
    assert main(["--mode", "paper"]) == 0
