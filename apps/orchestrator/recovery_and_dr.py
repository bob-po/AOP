"""Recovery and disaster preparedness (P36.8).

This module implements startup reconciliation, state consistency checks,
and disaster recovery procedures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from db import connect
from defaults import database_url as resolve_database_url


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConsistencyIssue(Enum):
    """Types of consistency issues."""

    ORPHANED_TASK = "orphaned_task"
    ORPHANED_NODE = "orphaned_node"
    STALE_RUNNING_NODE = "stale_running_node"
    MISMATCHED_STATUS = "mismatched_status"
    MISSING_ARTIFACT = "missing_artifact"
    DUPLICATE_REQUEST = "duplicate_request"
    PENDING_OUTBOX = "pending_outbox"


@dataclass
class ConsistencyCheck:
    """Result of a consistency check."""

    issue_type: ConsistencyIssue
    severity: str  # "critical", "warning", "info"
    description: str
    affected_ids: list[str]
    timestamp: datetime = None
    recommendation: str = ""

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = _utc_now()


class StartupReconciler:
    """Startup reconciliation for system recovery."""

    def __init__(self, database_url: str | None = None):
        self.database_url = resolve_database_url(database_url)
        self.issues: list[ConsistencyCheck] = []

    def run_full_reconciliation(self) -> list[ConsistencyCheck]:
        """Run full startup reconciliation."""
        self.issues = []
        self.check_orphaned_tasks()
        self.check_orphaned_nodes()
        self.check_stale_running_nodes()
        self.check_status_mismatches()
        self.check_pending_outbox_events()
        return self.issues

    def check_orphaned_tasks(self) -> None:
        """Check for tasks with no running nodes but status=running."""
        with connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT t.id::text as task_id, t.status
                FROM tasks t
                WHERE t.status = 'running'
                  AND NOT EXISTS (
                    SELECT 1 FROM task_nodes n
                    WHERE n.task_id = t.id AND n.status = 'running'
                  )
                """,
            ).fetchall()

            if rows:
                self.issues.append(
                    ConsistencyCheck(
                        issue_type=ConsistencyIssue.ORPHANED_TASK,
                        severity="critical",
                        description="Tasks marked as running but have no running nodes",
                        affected_ids=[row["task_id"] for row in rows],
                        recommendation="Mark tasks as failed or reclaim nodes",
                    )
                )

    def check_orphaned_nodes(self) -> None:
        """Check for nodes with no associated task."""
        with connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT n.id::text as node_id, n.node_key
                FROM task_nodes n
                WHERE NOT EXISTS (
                    SELECT 1 FROM tasks t
                    WHERE t.id = n.task_id
                )
                """,
            ).fetchall()

            if rows:
                self.issues.append(
                    ConsistencyCheck(
                        issue_type=ConsistencyIssue.ORPHANED_NODE,
                        severity="warning",
                        description="Nodes with no associated task",
                        affected_ids=[row["node_id"] for row in rows],
                        recommendation="Delete orphaned nodes",
                    )
                )

    def check_stale_running_nodes(self) -> None:
        """Check for nodes stuck in running state for too long."""
        stale_threshold_hours = 24

        with connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT id::text as node_id, node_key, started_at, updated_at
                FROM task_nodes
                WHERE status = 'running'
                  AND COALESCE(started_at, updated_at) < (now() - (%s || ' hours')::interval)
                """,
                (stale_threshold_hours,),
            ).fetchall()

            if rows:
                self.issues.append(
                    ConsistencyCheck(
                        issue_type=ConsistencyIssue.STALE_RUNNING_NODE,
                        severity="critical",
                        description=(
                            f"Nodes stuck in running state for > {stale_threshold_hours} hours"
                        ),
                        affected_ids=[row["node_id"] for row in rows],
                        recommendation="Mark as failed and reclaim",
                    )
                )

    def check_status_mismatches(self) -> None:
        """Check for task/node status mismatches."""
        with connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT t.id::text as task_id
                FROM tasks t
                WHERE t.status = 'completed'
                  AND EXISTS (
                    SELECT 1 FROM task_nodes n
                    WHERE n.task_id = t.id AND n.status = 'running'
                  )
                """,
            ).fetchall()

            if rows:
                self.issues.append(
                    ConsistencyCheck(
                        issue_type=ConsistencyIssue.MISMATCHED_STATUS,
                        severity="warning",
                        description="Tasks marked completed but have running nodes",
                        affected_ids=[row["task_id"] for row in rows],
                        recommendation="Update node statuses or recheck task status",
                    )
                )

    def check_pending_outbox_events(self) -> None:
        """Check for pending outbox events."""
        with connect(self.database_url) as conn:
            rows = conn.execute(
                """
                SELECT id::text as event_id, event_type, created_at
                FROM outbox_events
                WHERE status = 'pending'
                  AND created_at < (now() - '1 hour'::interval)
                ORDER BY created_at ASC
                LIMIT 100
                """,
            ).fetchall()

            if rows:
                self.issues.append(
                    ConsistencyCheck(
                        issue_type=ConsistencyIssue.PENDING_OUTBOX,
                        severity="warning",
                        description=f"{len(rows)} pending outbox events older than 1 hour",
                        affected_ids=[row["event_id"] for row in rows],
                        recommendation="Process pending outbox events",
                    )
                )

    def auto_fix_critical_issues(self) -> dict[str, Any]:
        """Automatically fix critical consistency issues.

        Dangerous on live systems — callers must opt in via
        ``RECOVERY_AUTO_FIX=1`` (see orchestrator startup).
        """
        fixed = {
            "orphaned_tasks": 0,
            "stale_nodes": 0,
        }

        with connect(self.database_url) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed',
                        error_message = 'Auto-fixed: orphaned task',
                        finished_at = now(),
                        updated_at = now()
                    WHERE status = 'running'
                      AND NOT EXISTS (
                        SELECT 1 FROM task_nodes n
                        WHERE n.task_id = tasks.id AND n.status = 'running'
                      )
                    RETURNING id::text
                    """,
                ).fetchall()
                fixed["orphaned_tasks"] = len(result)

                result = conn.execute(
                    """
                    UPDATE task_nodes
                    SET status = 'failed',
                        error_message = 'Auto-fixed: stale running node',
                        finished_at = now(),
                        updated_at = now()
                    WHERE status = 'running'
                      AND COALESCE(started_at, updated_at) < (now() - '24 hours'::interval)
                    RETURNING id::text
                    """,
                ).fetchall()
                fixed["stale_nodes"] = len(result)

        return fixed


class SystemHealthProbe:
    """Read-only health snapshot from Postgres (no fake backup/restore)."""

    def __init__(self, database_url: str | None = None):
        self.database_url = resolve_database_url(database_url)

    def get_system_health(self) -> dict[str, Any]:
        with connect(self.database_url) as conn:
            db_health = conn.execute("SELECT 1 as healthy").fetchone()
            task_stats = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM tasks
                GROUP BY status
                """,
            ).fetchall()
            node_stats = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM task_nodes
                GROUP BY status
                """,
            ).fetchall()
            return {
                "database_healthy": db_health["healthy"] == 1 if db_health else False,
                "task_stats": {row["status"]: row["count"] for row in task_stats},
                "node_stats": {row["status"]: row["count"] for row in node_stats},
                "timestamp": _utc_now().isoformat(),
            }
