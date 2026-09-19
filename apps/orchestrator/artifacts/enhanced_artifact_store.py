"""Enhanced artifact store with two-phase upload (P36.4).

This module implements two-phase artifact upload to prevent orphaned artifacts
on persistence failure, along with garbage collection and reference counting.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ArtifactReference:
    """Reference to an artifact with metadata."""
    uri: str
    name: str
    size: int
    content_type: str
    task_id: str
    node_key: str
    created_at: datetime
    reference_count: int = 1


class EnhancedArtifactStore:
    """Enhanced artifact store with two-phase upload and garbage collection."""
    
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
    
    def create_pending_artifact(
        self,
        task_id: str,
        node_key: str,
        name: str,
        content_type: str,
        size: int,
    ) -> str:
        """Create a pending artifact record for two-phase upload."""
        artifact_id = str(uuid.uuid4())
        uri = f"s3://aop-artifacts/tasks/{task_id}/{node_key}/{artifact_id}"
        
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                conn.execute(
                    """
                    INSERT INTO artifacts (
                      id, task_id, node_key, name, content_type, size, uri,
                      status, created_at, updated_at
                    ) VALUES (
                      %s::uuid, %s::uuid, %s, %s, %s, %s, %s, 'pending', %s, %s
                    )
                    """,
                    (
                        artifact_id,
                        task_id,
                        node_key,
                        name,
                        content_type,
                        size,
                        uri,
                        _utc_now(),
                        _utc_now(),
                    ),
                )
        
        return artifact_id
    
    def confirm_artifact_upload(
        self,
        artifact_id: str,
        actual_size: int | None = None,
    ) -> bool:
        """Confirm artifact upload in two-phase commit."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                updates = ["status = 'committed'", "updated_at = %s"]
                params = [_utc_now()]
                
                if actual_size is not None:
                    updates.append("size = %s")
                    params.append(actual_size)
                
                params.append(artifact_id)
                
                result = conn.execute(
                    f"""
                    UPDATE artifacts
                    SET {', '.join(updates)}
                    WHERE id = %s::uuid AND status = 'pending'
                    RETURNING id::text
                    """,
                    params,
                ).fetchone()
                
                return result is not None
    
    def rollback_artifact_upload(self, artifact_id: str) -> bool:
        """Rollback artifact upload if persistence fails."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    DELETE FROM artifacts
                    WHERE id = %s::uuid AND status = 'pending'
                    RETURNING id::text
                    """,
                    (artifact_id,),
                ).fetchone()
                
                return result is not None
    
    def increment_reference_count(self, artifact_id: str) -> bool:
        """Increment reference count for an artifact."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE artifacts
                    SET reference_count = reference_count + 1,
                        updated_at = %s
                    WHERE id = %s::uuid
                    RETURNING id::text
                    """,
                    (_utc_now(), artifact_id),
                ).fetchone()
                
                return result is not None
    
    def decrement_reference_count(self, artifact_id: str) -> bool:
        """Decrement reference count for an artifact."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    UPDATE artifacts
                    SET reference_count = reference_count - 1,
                        updated_at = %s
                    WHERE id = %s::uuid AND reference_count > 0
                    RETURNING id::text
                    """,
                    (_utc_now(), artifact_id),
                ).fetchone()
                
                return result is not None
    
    def cleanup_orphaned_artifacts(self, dry_run: bool = False) -> int:
        """Clean up artifacts with zero reference count."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                if dry_run:
                    rows = conn.execute(
                        """
                        SELECT id::text, uri, name
                        FROM artifacts
                        WHERE reference_count = 0 AND status = 'committed'
                        LIMIT 1000
                        """,
                    ).fetchall()
                    return len(rows)
                else:
                    result = conn.execute(
                        """
                        DELETE FROM artifacts
                        WHERE reference_count = 0 AND status = 'committed'
                        RETURNING id
                        """,
                    ).fetchall()
                    return len(result)
    
    def cleanup_pending_artifacts(self, older_than_hours: int = 24) -> int:
        """Clean up pending artifacts older than specified hours."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                result = conn.execute(
                    """
                    DELETE FROM artifacts
                    WHERE status = 'pending'
                      AND created_at < (now() - (%s || ' hours')::interval)
                    RETURNING id
                    """,
                    (older_than_hours,),
                ).fetchall()
                return len(result)
    
    def get_artifact_reference(self, artifact_id: str) -> ArtifactReference | None:
        """Get artifact reference by ID."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT id::text, uri, name, size, content_type,
                       task_id::text, node_key, created_at, reference_count
                FROM artifacts
                WHERE id = %s::uuid
                """,
                (artifact_id,),
            ).fetchone()
            
            if not row:
                return None
            
            return ArtifactReference(
                uri=row["uri"],
                name=row["name"],
                size=row["size"],
                content_type=row["content_type"],
                task_id=row["task_id"],
                node_key=row["node_key"],
                created_at=row["created_at"],
                reference_count=row["reference_count"],
            )
    
    def get_artifacts_by_task(self, task_id: str) -> list[ArtifactReference]:
        """Get all artifacts for a task."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT id::text, uri, name, size, content_type,
                       task_id::text, node_key, created_at, reference_count
                FROM artifacts
                WHERE task_id = %s::uuid AND status = 'committed'
                ORDER BY created_at ASC
                """,
                (task_id,),
            ).fetchall()
            
            return [
                ArtifactReference(
                    uri=row["uri"],
                    name=row["name"],
                    size=row["size"],
                    content_type=row["content_type"],
                    task_id=row["task_id"],
                    node_key=row["node_key"],
                    created_at=row["created_at"],
                    reference_count=row["reference_count"],
                )
                for row in rows
            ]
    
    def get_artifact_stats(self) -> dict[str, Any]:
        """Get artifact statistics."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) as count, SUM(size) as total_size
                FROM artifacts
                GROUP BY status
                """,
            ).fetchall()
            
            stats = {}
            for row in rows:
                stats[row["status"]] = {
                    "count": row["count"],
                    "total_size": row["total_size"] or 0,
                }
            
            return stats


# Singleton instance
_enhanced_artifact_store: EnhancedArtifactStore | None = None


def get_enhanced_artifact_store() -> EnhancedArtifactStore:
    """Get or create the singleton enhanced artifact store."""
    global _enhanced_artifact_store
    if _enhanced_artifact_store is None:
        _enhanced_artifact_store = EnhancedArtifactStore()
    return _enhanced_artifact_store
