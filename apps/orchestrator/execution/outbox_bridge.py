"""Phase 4 — write execution events to outbox (same txn when possible)."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

EXECUTION_STREAM = "a2a.execution.events"


def write_execution_outbox(
    conn,
    *,
    event_id: str,
    event_type: str,
    root_task_id: str | None,
    correlation_id: str | None,
    task_id: str | None,
    agent_id: str | None,
    sequence: int | None,
    payload: dict[str, Any],
) -> None:
    """Insert outbox row inside an open transaction (conn must be in txn)."""
    from psycopg.types.json import Jsonb

    body = {
        "event_type": event_type,
        "data": {
            "event_id": event_id,
            "root_task_id": root_task_id,
            "correlation_id": correlation_id,
            "task_id": task_id,
            "agent_id": agent_id,
            "sequence": sequence,
            **payload,
        },
    }
    conn.execute(
        """
        INSERT INTO outbox_events (
          event_type, payload, target_stream, status, created_at,
          event_id, aggregate_type, aggregate_id, root_task_id,
          correlation_id, sequence
        ) VALUES (
          'execution_event', %s, %s, 'pending', now(),
          %s, 'execution', %s, %s, %s, %s
        )
        ON CONFLICT (event_id) WHERE event_id IS NOT NULL DO NOTHING
        """,
        (
            Jsonb(body),
            EXECUTION_STREAM,
            event_id,
            task_id,
            root_task_id,
            correlation_id,
            sequence,
        ),
    )


def emit_outbox_standalone(
    *,
    event_id: str,
    event_type: str,
    root_task_id: str | None = None,
    correlation_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
    sequence: int | None = None,
    payload: dict[str, Any] | None = None,
    database_url: str | None = None,
) -> bool:
    """Best-effort outbox write outside a record txn (memory store path)."""
    try:
        from db import connect

        url = database_url or os.getenv(
            "DATABASE_URL", "postgresql://aop:aop@127.0.0.1:5432/aop"
        )
        with connect(url) as conn:
            with conn.transaction():
                write_execution_outbox(
                    conn,
                    event_id=event_id,
                    event_type=event_type,
                    root_task_id=root_task_id,
                    correlation_id=correlation_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    sequence=sequence,
                    payload=dict(payload or {}),
                )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("outbox standalone write skipped: %s", exc)
        return False


__all__ = ["write_execution_outbox", "emit_outbox_standalone", "EXECUTION_STREAM"]
