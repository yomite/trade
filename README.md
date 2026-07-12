# Trading Bot

Autonomous, self-learning crypto trading bot for **Bybit spot** (BTC/USDT,
ETH/USDT). Runs natively on Ubuntu — **no Docker** — with a local Python 3.11
virtual environment and (in production) systemd services on a DigitalOcean
droplet.

> **The specification is [CLAUDE.md](CLAUDE.md).** It is the source of truth for
> architecture, hard constraints, and build order. The phased build with its
> per-phase operator checklists is in [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Status

**Phase 0 — project foundation.** Repo skeleton, config, logging, constants,
tooling, and CI. No trading logic yet; that is built in later phases (data →
risk → backtest → strategies → paper → live → learning → monitoring).

## Quick start (Ubuntu)

Full, copy-pasteable setup — including PostgreSQL 16, the TimescaleDB extension,
and the ta-lib C library — is in **[docs/dev-setup-ubuntu.md](docs/dev-setup-ubuntu.md)**.
Once the system packages and dev database exist:

```bash
git clone https://github.com/yomite/trade.git ~/tradingbot
cd ~/tradingbot
make install            # creates .venv (Python 3.11), installs core + dev deps
cp .env.example .env    # then fill DATABASE_URL (and later: Bybit, Telegram)
make test               # Phase 0 Definition of Done: this passes
```

The heavy ML stack (PyTorch, XGBoost, LightGBM, …) is a separate extra, needed
from Phase 4 onward:

```bash
make install-all        # core + dev + ml + backup + macro
```

## Common commands

| Command | What it does |
|---|---|
| `make install` | Create the venv, install core + dev deps, register pre-commit |
| `make install-all` | As above plus the ML / backup / macro extras |
| `make test` | Full test suite with coverage |
| `make test-fast` | Fast unit tests only (what pre-commit runs) |
| `make lint` | Ruff lint + format check |
| `make typecheck` | `mypy --strict` |
| `make run-paper` | Run the bot in paper mode (Phase 5+) |
| `make backtest` | Run a backtest (Phase 3+) |
| `make healthcheck` | Pre-trade system health validation (Phase 6+) |

## Layout

See [CLAUDE.md §9](CLAUDE.md) for the full tree. Top level:

```
src/            # the bot, organized into the five layers of the spec
  common/       # config, logging, time, shared types  (Phase 0)
  constants.py  # HARD CONSTRAINTS from Section 4       (Phase 0)
config/         # base.yaml + paper/live/backtest overrides
tests/          # unit / integration / property / fixtures
deploy/         # systemd units + bootstrap scripts (no Docker) (Phase 6+)
docs/           # setup + runbook
```

## Safety

Every risk limit, circuit breaker, and the spot-only lock live in
[`src/constants.py`](src/constants.py) and are enforced in code. They are never
relaxed at runtime — config may only *tighten* them. See
[CLAUDE.md §4](CLAUDE.md) for the constraints and their rationale.
