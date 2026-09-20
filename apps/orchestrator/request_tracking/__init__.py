"""Request tracking for A2A idempotency (P36.1)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from db import connect
from psycopg.types.json import Jsonb

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RequestTrackingService:
    """Service for tracking A2A requests with idempotency keys."""

    def __init__(
        self,
        database_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.tenant_id = tenant_id

    def generate_idempotency_key(self) -> str:
        """Generate a unique idempotency key for an A2A request."""
        return f"req_{uuid.uuid4().hex}"

    def track_request(
        self,
        idempotency_key: str,
        task_id: str,
        node_id: str,
        agent_id: str,
        request_json: dict[str, Any],
    ) -> dict[str, Any]:
        """Track a new A2A request."""
        with connect(self.database_url) as conn:
            with conn.transaction():
                # First check if request already exists
                existing = conn.execute(
                    """
                    SELECT id::text, idempotency_key, status, response_json, error_message, created_at
                    FROM a2a_requests
                    WHERE idempotency_key = %s
                    """,
                    (idempotency_key,),
                ).fetchone()
                
                if existing:
                    return dict(existing)
                
                # Insert new request
                row = conn.execute(
                    """
                    INSERT INTO a2a_requests (
                      idempotency_key, task_id, node_id, agent_id,
                      status, request_json, created_at, updated_at
                    ) VALUES (
                      %s, %s::uuid, %s::uuid, %s::uuid,
                      'pending', %s::jsonb, %s, %s
                    )
                    RETURNING id::text, idempotency_key, status, created_at
                    """,
                    (
                        idempotency_key,
                        task_id,
                        node_id,
                        agent_id,
                        Jsonb(request_json),
                        _utc_now(),
                        _utc_now(),
                    ),
                ).fetchone()
                return dict(row) if row else {}

    def get_request(self, idempotency_key: str) -> dict[str, Any] | None:
        """Get an existing request by idempotency key."""
        with connect(self.database_url) as conn:
            row = conn.execute(
                """
                SELECT id::text, idempotency_key, task_id::text, node_id::text,
                       agent_id::text, status, request_json, response_json,
                       error_message, created_at, updated_at, finished_at
                FROM a2a_requests
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            ).fetchone()
            return dict(row) if row else None

    def mark_request_running(
        self,
        idempotency_key: str,
    ) -> bool:
        """Mark a request as running."""
        with connect(self.database_url) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE a2a_requests
                    SET status = 'running', updated_at = %s
                    WHERE idempotency_key = %s AND status = 'pending'
                    RETURNING id::text
                    """,
                    (_utc_now(), idempotency_key),
                ).fetchone()
                return result is not None

    def mark_request_completed(
        self,
        idempotency_key: str,
        response_json: dict[str, Any],
    ) -> bool:
        """Mark a request as completed with response."""
        with connect(self.database_url) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE a2a_requests
                    SET status = 'completed',
                        response_json = %s::jsonb,
                        updated_at = %s,
                        finished_at = %s
                    WHERE idempotency_key = %s AND status IN ('pending', 'running')
                    RETURNING id::text
                    """,
                    (Jsonb(response_json), _utc_now(), _utc_now(), idempotency_key),
                ).fetchone()
                return result is not None

    def mark_request_failed(
        self,
        idempotency_key: str,
        error_message: str,
    ) -> bool:
        """Mark a request as failed."""
        with connect(self.database_url) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE a2a_requests
                    SET status = 'failed',
                        error_message = %s,
                        updated_at = %s,
                        finished_at = %s
                    WHERE idempotency_key = %s AND status IN ('pending', 'running')
                    RETURNING id::text
                    """,
                    (error_message, _utc_now(), _utc_now(), idempotency_key),
                ).fetchone()
                return result is not None

    def mark_request_unknown(
        self,
        idempotency_key: str,
        reason: str = "timeout",
    ) -> bool:
        """Mark a request as unknown (timeout/uncertain result)."""
        with connect(self.database_url) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE a2a_requests
                    SET status = 'unknown',
                        error_message = %s,
                        updated_at = %s,
                        finished_at = %s
                    WHERE idempotency_key = %s AND status IN ('pending', 'running')
                    RETURNING id::text
                    """,
                    (reason, _utc_now(), _utc_now(), idempotency_key),
                ).fetchone()
                return result is not None

    def is_request_completed(self, idempotency_key: str) -> bool:
        """Check if a request is already completed."""
        request = self.get_request(idempotency_key)
        return request is not None and request.get("status") == "completed"

    def get_cached_response(self, idempotency_key: str) -> dict[str, Any] | None:
        """Get cached response for a completed request."""
        request = self.get_request(idempotency_key)
        if request and request.get("status") == "completed":
            response_json = request.get("response_json")
            if isinstance(response_json, str):
                import json
                response_json = json.loads(response_json)
            return response_json
        return None


# Singleton instance for application use
_tracking_service: RequestTrackingService | None = None


def get_request_tracking_service() -> RequestTrackingService:
    """Get or create the singleton request tracking service."""
    global _tracking_service
    if _tracking_service is None:
        _tracking_service = RequestTrackingService()
    return _tracking_service
