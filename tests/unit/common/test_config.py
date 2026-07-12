"""Tests for the layered config loader (Section 12)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from src.common.config import load_config
from src.common.types import Mode


@pytest.mark.fast
def test_loads_base_and_paper_override(config_dir: Path) -> None:
    cfg = load_config(mode="paper", config_dir=config_dir)
    assert cfg.mode == Mode.PAPER
    assert cfg.exchange.name == "bybit"
    assert cfg.exchange.testnet is True  # paper.yaml overrides base
    assert "BTC/USDT" in cfg.universe.symbols
    assert cfg.risk.risk_per_trade_pct == Decimal("1.0")


@pytest.mark.fast
def test_mode_selects_override_file(config_dir: Path) -> None:
    live = load_config(mode="live", config_dir=config_dir)
    assert live.mode == Mode.LIVE
    assert live.exchange.testnet is False


@pytest.mark.fast
def test_explicit_mode_beats_bot_mode_env(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CLI/explicit mode is the highest layer (Section 12.1) — it wins over BOT_MODE.
    monkeypatch.setenv("BOT_MODE", "paper")
    cfg = load_config(mode="live", config_dir=config_dir)
    assert cfg.mode == Mode.LIVE


@pytest.mark.fast
def test_env_var_override_nested(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # BOT_RISK__MAX_CONCURRENT tightens the limit from 3 to 2 (Section 12.1 layer 3).
    monkeypatch.setenv("BOT_RISK__MAX_CONCURRENT", "2")
    cfg = load_config(mode="paper", config_dir=config_dir)
    assert cfg.risk.max_concurrent == 2


@pytest.mark.fast
def test_env_substitution_in_yaml(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
    cfg = load_config(mode="paper", config_dir=config_dir)
    assert cfg.monitoring.telegram_chat_id == "123456789"


@pytest.mark.fast
def test_unset_telegram_chat_id_becomes_none(
    config_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    cfg = load_config(mode="paper", config_dir=config_dir)
    assert cfg.monitoring.telegram_chat_id is None


@pytest.mark.fast
def test_cli_override_highest_priority(config_dir: Path) -> None:
    cfg = load_config(
        mode="paper",
        config_dir=config_dir,
        cli_overrides={"logging": {"level": "ERROR"}},
    )
    assert cfg.logging.level == "ERROR"


@pytest.mark.fast
def test_rejects_config_looser_than_hard_constraint(config_dir: Path) -> None:
    # risk_per_trade 2.0% exceeds the 1.0% HARD CONSTRAINT (Section 4.1).
    with pytest.raises(ValidationError, match="exceeds hard constraint"):
        load_config(
            mode="paper",
            config_dir=config_dir,
            cli_overrides={"risk": {"risk_per_trade_pct": 2.0}},
        )


@pytest.mark.fast
def test_rejects_non_spot_category(config_dir: Path) -> None:
    # Section 16.4.4: spot only.
    with pytest.raises(ValidationError, match="spot"):
        load_config(
            mode="paper",
            config_dir=config_dir,
            cli_overrides={"exchange": {"category": "linear"}},
        )


@pytest.mark.fast
def test_rejects_unknown_key(config_dir: Path) -> None:
    with pytest.raises(ValidationError):
        load_config(
            mode="paper",
            config_dir=config_dir,
            cli_overrides={"risk": {"totally_made_up_field": 1}},
        )
