"""Recovery and disaster preparedness (P36.8).

This module implements startup reconciliation, state consistency checks,
backup verification, and disaster recovery procedures.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import psycopg
from psycopg.rows import dict_row


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
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.issues: list[ConsistencyCheck] = []
    
    def run_full_reconciliation(self) -> list[ConsistencyCheck]:
        """Run full startup reconciliation."""
        self.issues = []
        
        # Check for orphaned tasks
        self.check_orphaned_tasks()
        
        # Check for orphaned nodes
        self.check_orphaned_nodes()
        
        # Check for stale running nodes
        self.check_stale_running_nodes()
        
        # Check for status mismatches
        self.check_status_mismatches()
        
        # Check for missing artifacts
        self.check_missing_artifacts()
        
        # Check for pending outbox events
        self.check_pending_outbox_events()
        
        return self.issues
    
    def check_orphaned_tasks(self) -> None:
        """Check for tasks with no running nodes but status=running."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
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
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
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
        
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
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
                        description=f"Nodes stuck in running state for > {stale_threshold_hours} hours",
                        affected_ids=[row["node_id"] for row in rows],
                        recommendation="Mark as failed and reclaim",
                    )
                )
    
    def check_status_mismatches(self) -> None:
        """Check for task/node status mismatches."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            # Tasks marked completed but have running nodes
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
    
    def check_missing_artifacts(self) -> None:
        """Check for missing artifacts referenced by nodes."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT n.id::text as node_id, n.artifact_uris
                FROM task_nodes n
                WHERE n.artifact_uris IS NOT NULL
                  AND n.artifact_uris != '[]'::jsonb
                  AND NOT EXISTS (
                    SELECT 1 FROM artifacts a
                    WHERE a.uri = ANY(n.artifact_uris)
                  )
                """,
            ).fetchall()
            
            if rows:
                self.issues.append(
                    ConsistencyCheck(
                        issue_type=ConsistencyIssue.MISSING_ARTIFACT,
                        severity="warning",
                        description="Nodes reference missing artifacts",
                        affected_ids=[row["node_id"] for row in rows],
                        recommendation="Remove artifact references or restore artifacts",
                    )
                )
    
    def check_pending_outbox_events(self) -> None:
        """Check for pending outbox events."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
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
        """Automatically fix critical consistency issues."""
        fixed = {
            "orphaned_tasks": 0,
            "stale_nodes": 0,
        }
        
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                # Fix orphaned tasks by marking as failed
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
                
                # Fix stale running nodes
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


class DisasterRecoveryManager:
    """Disaster recovery management."""
    
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
    
    def create_backup_snapshot(self) -> str:
        """Create a backup snapshot (placeholder for actual backup implementation)."""
        # This would integrate with your backup system
        # For now, return a timestamp
        return _utc_now().isoformat()
    
    def verify_backup_integrity(self, backup_id: str) -> bool:
        """Verify backup integrity (placeholder)."""
        # This would check backup checksums and restore capability
        return True
    
    def restore_from_backup(self, backup_id: str) -> bool:
        """Restore from backup (placeholder)."""
        # This would implement actual restore logic
        return True
    
    def get_system_health(self) -> dict[str, Any]:
        """Get overall system health status."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            # Database connection check
            db_health = conn.execute("SELECT 1 as healthy").fetchone()
            
            # Task statistics
            task_stats = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM tasks
                GROUP BY status
                """,
            ).fetchall()
            
            # Node statistics
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


# Singleton instances
_startup_reconciler: StartupReconciler | None = None
_disaster_recovery_manager: DisasterRecoveryManager | None = None


def get_startup_reconciler() -> StartupReconciler:
    """Get or create the singleton startup reconciler."""
    global _startup_reconciler
    if _startup_reconciler is None:
        _startup_reconciler = StartupReconciler()
    return _startup_reconciler


def get_disaster_recovery_manager() -> DisasterRecoveryManager:
    """Get or create the singleton disaster recovery manager."""
    global _disaster_recovery_manager
    if _disaster_recovery_manager is None:
        _disaster_recovery_manager = DisasterRecoveryManager()
    return _disaster_recovery_manager
