"""Load secrets from ``.env`` into the process environment.

Secrets (DATABASE_URL, API keys) live only in ``.env`` (Section 12.3), never in
config files. Call :func:`load_env` once at process start, before reading config
or connecting to the database.
"""

from __future__ import annotations

from dotenv import load_dotenv


def load_env() -> None:
    """Load ``.env`` from the current directory or nearest parent. Idempotent."""
    load_dotenv(override=False)
