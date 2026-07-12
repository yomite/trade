# Trading bot — common commands (Section 10, Phase 0 DoD).
# No Docker anywhere (Section 0.1). Everything runs in a local Python 3.11 venv.

PYTHON := python3.11
VENV := .venv
BIN := $(VENV)/bin

.DEFAULT_GOAL := help
.PHONY: help venv install install-all lint format typecheck test test-fast \
        healthcheck run-paper backtest clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV):  ## Create the 3.11 virtual environment
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

venv: $(VENV)

install: $(VENV)  ## Install core + dev deps (fast; enough for tests & lint)
	$(BIN)/pip install -e ".[dev]"
	$(BIN)/pre-commit install || true

install-all: $(VENV)  ## Install everything incl. the ML stack (Phase 4+)
	$(BIN)/pip install -e ".[dev,ml,backup,macro]"

lint:  ## Ruff lint + format check
	$(BIN)/ruff check src tests scripts
	$(BIN)/ruff format --check src tests scripts

format:  ## Auto-format with ruff
	$(BIN)/ruff format src tests scripts
	$(BIN)/ruff check --fix src tests scripts

typecheck:  ## mypy --strict
	$(BIN)/mypy src

test:  ## Full test suite with coverage
	$(BIN)/pytest --cov --cov-report=term-missing

test-fast:  ## Only fast unit tests (used by pre-commit)
	$(BIN)/pytest -m fast

healthcheck:  ## Pre-trade system health validation (Section 23.1)
	$(BIN)/python scripts/healthcheck.py

run-paper:  ## Run the bot in paper-trading mode (Phase 5+)
	$(BIN)/python -m src.main --mode paper

backtest:  ## Run a backtest (Phase 3+)
	$(BIN)/python scripts/run_backtest.py

clean:  ## Remove caches and build artifacts
	rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage htmlcov *.egg-info build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
