"""Layered, validated configuration (Section 12).

Load order, each layer overriding the previous (Section 12.1):

1. ``config/base.yaml`` — defaults
2. ``config/{mode}.yaml`` — mode-specific (paper | live | backtest)
3. Environment variables (prefix ``BOT_``; nest with ``__``, e.g.
   ``BOT_RISK__RISK_PER_TRADE_PCT=0.5``)
4. CLI args (passed in as a dict of overrides)

``${VAR}`` and ``${VAR:-default}`` references inside YAML values are expanded
from the environment. Invalid config is a startup failure (Section 12.1).

The risk section is validated to never be *looser* than the HARD CONSTRAINTS in
``src.constants`` — config may tighten a limit but never relax it.
"""

from __future__ import annotations

import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, BeforeValidator, ConfigDict, field_validator, model_validator

from src import constants
from src.common.types import Mode

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _to_decimal(value: Any) -> Any:
    """Coerce YAML floats to Decimal via ``str`` to avoid binary-float noise.

    ``Decimal(0.6)`` is ``0.59999…``; ``Decimal(str(0.6))`` is exactly ``0.6``.
    Without this, a config value equal to a hard constraint could read as
    marginally below/above it and fail validation.
    """
    return Decimal(str(value)) if isinstance(value, float) else value


# Decimal config field that parses cleanly from YAML floats.
DecimalField = Annotated[Decimal, BeforeValidator(_to_decimal)]


class _Strict(BaseModel):
    """Base model that rejects unknown keys so config typos fail loudly."""

    model_config = ConfigDict(extra="forbid")


class ExchangeConfig(_Strict):
    name: str
    testnet: bool = False
    category: str = "spot"

    @field_validator("category")
    @classmethod
    def _spot_only(cls, v: str) -> str:
        # HARD CONSTRAINT (Section 16.4.4): spot only.
        if v != constants.ALLOWED_EXCHANGE_CATEGORY:
            raise ValueError(
                f"exchange.category must be '{constants.ALLOWED_EXCHANGE_CATEGORY}', got '{v}'"
            )
        return v


class UniverseConfig(_Strict):
    symbols: list[str]
    timeframes: list[str]


class RiskConfig(_Strict):
    risk_per_trade_pct: DecimalField
    max_position_pct: DecimalField
    max_concurrent: int
    kelly_cap: DecimalField
    daily_loss_pause_pct: DecimalField
    weekly_loss_pause_pct: DecimalField
    shutdown_drawdown_pct: DecimalField
    consec_losses_suspend: int
    min_confidence: DecimalField
    cost_edge_multiple: DecimalField
    min_trade_notional_usd: DecimalField

    @model_validator(mode="after")
    def _not_looser_than_hard_constraints(self) -> RiskConfig:
        """Config may tighten a hard limit but never relax it (Section 4)."""
        checks: list[tuple[str, Decimal | int, Decimal | int, str]] = [
            ("risk_per_trade_pct", self.risk_per_trade_pct, constants.RISK_PER_TRADE_PCT, "max"),
            ("max_position_pct", self.max_position_pct, constants.MAX_POSITION_PCT, "max"),
            ("max_concurrent", self.max_concurrent, constants.MAX_CONCURRENT_POSITIONS, "max"),
            ("kelly_cap", self.kelly_cap, constants.KELLY_FRACTION_CAP, "max"),
            (
                "daily_loss_pause_pct",
                self.daily_loss_pause_pct,
                constants.DAILY_LOSS_PAUSE_PCT,
                "max",
            ),
            (
                "weekly_loss_pause_pct",
                self.weekly_loss_pause_pct,
                constants.WEEKLY_LOSS_PAUSE_PCT,
                "max",
            ),
            (
                "shutdown_drawdown_pct",
                self.shutdown_drawdown_pct,
                constants.TOTAL_DRAWDOWN_SHUTDOWN_PCT,
                "max",
            ),
            (
                "consec_losses_suspend",
                self.consec_losses_suspend,
                constants.CONSEC_LOSSES_SUSPEND,
                "max",
            ),
            ("min_confidence", self.min_confidence, constants.MIN_MODEL_CONFIDENCE, "min"),
            ("cost_edge_multiple", self.cost_edge_multiple, constants.COST_EDGE_MULTIPLE, "min"),
            (
                "min_trade_notional_usd",
                self.min_trade_notional_usd,
                constants.MIN_TRADE_NOTIONAL_USD,
                "min",
            ),
        ]
        for name, value, limit, direction in checks:
            if direction == "max" and value > limit:
                raise ValueError(
                    f"risk.{name}={value} exceeds hard constraint {limit}; config may only tighten it"
                )
            if direction == "min" and value < limit:
                raise ValueError(
                    f"risk.{name}={value} is below hard constraint {limit}; config may only raise it"
                )
        return self


class ExecutionConfig(_Strict):
    default_order_type: str
    limit_price_offset_bps: DecimalField
    max_slippage_bps: DecimalField
    stop_registration_timeout_s: float = 3.0
    reconcile_interval_s: int = 60


class DataConfig(_Strict):
    warmup_seconds: int = 300
    stale_bar_seconds: int = 60
    max_clock_drift_seconds: float = 1.0


class ModelsConfig(_Strict):
    ensemble_weights: dict[str, float]
    min_confidence: DecimalField
    retrain_schedule: dict[str, str]


class MonitoringConfig(_Strict):
    telegram_chat_id: str | None = None
    alert_levels: list[str] = []
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8000

    @field_validator("telegram_chat_id", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        # An unresolved ${TELEGRAM_CHAT_ID} expands to "" in dev — treat as unset.
        return None if v == "" else v


class LoggingConfig(_Strict):
    level: str = "INFO"
    format: str = "json"


class Config(_Strict):
    """Fully validated runtime configuration."""

    mode: Mode
    exchange: ExchangeConfig
    universe: UniverseConfig
    risk: RiskConfig
    execution: ExecutionConfig
    data: DataConfig = DataConfig()
    models: ModelsConfig
    monitoring: MonitoringConfig
    logging: LoggingConfig = LoggingConfig()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (returns a new dict)."""
    result = dict(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = value
    return result


def _expand_env(value: Any) -> Any:
    """Recursively expand ``${VAR}`` / ``${VAR:-default}`` in string values."""
    if isinstance(value, str):

        def _sub(match: re.Match[str]) -> str:
            var, default = match.group(1), match.group(2)
            return os.environ.get(var, default if default is not None else "")

        return _ENV_PATTERN.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def _coerce_scalar(raw: str) -> Any:
    """Best-effort YAML-style scalar parse for env-var override values."""
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def _apply_env_overrides(data: dict[str, Any], prefix: str = "BOT_") -> dict[str, Any]:
    """Overlay ``BOT_*`` env vars. ``__`` denotes nesting (Section 12.1 layer 3)."""
    result = data
    for env_key, raw in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        path = [part.lower() for part in env_key[len(prefix) :].split("__")]
        cursor = result
        for part in path[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[path[-1]] = _coerce_scalar(raw)
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping at the top level")
    return loaded


def load_config(
    mode: str | None = None,
    config_dir: Path | str = "config",
    cli_overrides: dict[str, Any] | None = None,
) -> Config:
    """Load and validate configuration through all four layers (Section 12.1).

    Args:
        mode: Overrides the base ``mode`` and selects ``config/{mode}.yaml``.
            Falls back to the ``BOT_MODE`` env var, then ``base.yaml``.
        config_dir: Directory holding the YAML files.
        cli_overrides: Highest-priority overrides (a nested dict).

    Returns:
        A validated :class:`Config`.

    Raises:
        pydantic.ValidationError: if the merged config is invalid.
    """
    config_dir = Path(config_dir)
    merged = _load_yaml(config_dir / "base.yaml")

    selected_mode = mode or os.environ.get("BOT_MODE") or merged.get("mode")
    if selected_mode:
        merged = _deep_merge(merged, _load_yaml(config_dir / f"{selected_mode}.yaml"))
        merged["mode"] = selected_mode

    merged = _apply_env_overrides(merged)
    if cli_overrides:
        merged = _deep_merge(merged, cli_overrides)

    merged = _expand_env(merged)
    return Config.model_validate(merged)
