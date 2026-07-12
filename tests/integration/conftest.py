"""Fixtures for integration tests that touch the real database.

Reads only ``DATABASE_URL`` (from the environment or ``.env``) instead of loading
the whole ``.env`` into ``os.environ`` — that would leak ``BOT_*`` vars into the
unit tests and break config-precedence assertions.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from src.data.storage.timescale import Database

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _database_url() -> str | None:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env_file = _REPO_ROOT / ".env"
    if env_file.exists():
        match = re.search(r"^DATABASE_URL=(.+)$", env_file.read_text(), flags=re.M)
        if match:
            return match.group(1).strip()
    return None


@pytest.fixture(scope="session")
def db() -> Database:
    """A Database against the local TimescaleDB. Skips if unavailable."""
    url = _database_url()
    if not url or "CHANGEME" in url:
        pytest.skip("DATABASE_URL not configured")
    database = Database(url=url)
    try:
        reachable = database.ping()
    except Exception as exc:
        pytest.skip(f"database not reachable: {type(exc).__name__}")
    if not reachable:
        pytest.skip("timescaledb extension not present")
    database.apply_schema()
    return database
