"""Shared fixtures for orchestrator tests."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

# Allow `from planner...` / `from scheduler...` when running from apps/orchestrator
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://aop:aop@127.0.0.1:5432/aop",
)


def _pg_available() -> bool:
    try:
        import psycopg

        with psycopg.connect(DATABASE_URL, connect_timeout=2) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


requires_pg = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL not reachable (set DATABASE_URL or start docker compose postgres)",
)


@pytest.fixture(scope="session")
def database_url() -> str:
    return DATABASE_URL


@pytest.fixture
def agent_id(database_url: str) -> str:
    """Insert a disposable online agent and return its id."""
    import psycopg
    from psycopg.rows import dict_row

    agent_uuid = str(uuid.uuid4())
    agent_key = f"test-agent-{agent_uuid[:8]}"
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        with conn.transaction():
            conn.execute(
                """
                INSERT INTO agents (id, tenant_id, agent_key, name, status, priority)
                VALUES (%s::uuid, %s::uuid, %s, %s, 'online', 100)
                """,
                (agent_uuid, DEFAULT_TENANT, agent_key, "Test Agent"),
            )
            conn.execute(
                """
                INSERT INTO agent_skills (agent_id, skill_id, name)
                VALUES (%s::uuid, 'web-search', 'Web Search')
                """,
                (agent_uuid,),
            )
    yield agent_uuid
    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            # Clear FKs before deleting the disposable agent
            conn.execute(
                """
                UPDATE task_nodes
                SET assigned_agent_id = NULL
                WHERE assigned_agent_id = %s::uuid
                """,
                (agent_uuid,),
            )
            conn.execute(
                "DELETE FROM agent_runs WHERE agent_id = %s::uuid",
                (agent_uuid,),
            )
            conn.execute(
                "DELETE FROM agent_skills WHERE agent_id = %s::uuid",
                (agent_uuid,),
            )
            conn.execute(
                "DELETE FROM agent_endpoints WHERE agent_id = %s::uuid",
                (agent_uuid,),
            )
            conn.execute("DELETE FROM agents WHERE id = %s::uuid", (agent_uuid,))
