"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def config_dir() -> Path:
    """Path to the repo's config/ directory (base.yaml, mode overrides)."""
    return REPO_ROOT / "config"
