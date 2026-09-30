"""Shared orchestrator defaults (tenant id + local Postgres DSN).

Import from here instead of re-declaring the same UUID / DSN literals.
"""

from __future__ import annotations

import os

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_DATABASE_URL = "postgresql://aop:aop@127.0.0.1:5432/aop"


def database_url(explicit: str | None = None) -> str:
    """Resolve Postgres URL: explicit arg, else ``DATABASE_URL``, else local default."""
    if explicit:
        return explicit
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
