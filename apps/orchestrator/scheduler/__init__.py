"""Scheduler: persist DAG nodes/deps and mark READY roots."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from planner.dag import PlanNode, TaskPlan, ready_node_ids, validate_plan

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Request tracking will be imported lazily in methods to avoid circular dependency
# Outbox pattern for P36.2 distributed transactions (lazy import)

__all__ = [
    "DEFAULT_TENANT_ID",
    "Scheduler",
    "ScheduleResult",
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ScheduleResult:
    task_id: str
    status: str
    ready_nodes: list[str]
    nodes: list[dict[str, Any]]
    ready_jobs: list[dict[str, Any]] = field(default_factory=list)

class Scheduler:
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
        self._request_tracking_service = None  # Lazy-loaded
        self._outbox_processor = None  # Lazy-loaded for P36.2

    def create_task(
        self,
        *,
        goal: str,
        plan: TaskPlan,
        user_id: str | None = None,
        input_extra: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        plan_source: str = "planner",
        tenant_id: str | None = None,
    ) -> ScheduleResult:
        validate_plan(plan)
        tid = tenant_id or self.tenant_id

        input_json = {"type": "text", "content": goal}
        if input_extra:
            input_json.update(input_extra)

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                task_id = str(uuid.uuid4())
                now = _utc_now()
                conn.execute(
                    """
                    INSERT INTO tasks (
                      id, tenant_id, user_id, title, input_json, status, progress,
                      plan_json, workflow_id, created_at, updated_at, started_at
                    ) VALUES (
                      %s::uuid, %s::uuid, %s, %s, %s::jsonb, 'planning', 0,
                      %s::jsonb, %s::uuid, %s, %s, %s
                    )
                    """,
                    (
                        task_id,
                        tid,
                        user_id,
                        plan.title,
                        Jsonb(input_json),
                        Jsonb(plan.to_dict()),
                        workflow_id,
                        now,
                        now,
                        now,
                    ),
                )
                self._append_event(
                    conn,
                    task_id,
                    None,
                    "task.created",
                    "Task Created",
                    {"goal": goal, "workflow_id": workflow_id, "plan_source": plan_source},
                )
                planned_msg = (
                    f"Workflow applied with {len(plan.nodes)} nodes"
                    if plan_source == "workflow"
                    else f"Planner decomposed into {len(plan.nodes)} nodes"
                )
                self._append_event(
                    conn,
                    task_id,
                    None,
                    "task.planned",
                    planned_msg,
                    plan.to_dict(),
                )

                node_rows: dict[str, str] = {}  # node_key -> uuid
                skill_by_key = {n.id: n.skill for n in plan.nodes}
                for node in plan.nodes:
                    node_uuid = str(uuid.uuid4())
                    node_rows[node.id] = node_uuid
                    conn.execute(
                        """
                        INSERT INTO task_nodes (
                          id, task_id, node_key, skill, status, input_json,
                          attempt, max_retry, created_at, updated_at
                        ) VALUES (
                          %s::uuid, %s::uuid, %s, %s, 'pending', %s::jsonb,
                          0, 3, %s, %s
                        )
                        """,
                        (
                            node_uuid,
                            task_id,
                            node.id,
                            node.skill,
                            Jsonb({"goal": goal, "node_id": node.id}),
                            now,
                            now,
                        ),
                    )

                for node in plan.nodes:
                    for dep in node.depends_on:
                        conn.execute(
                            """
                            INSERT INTO task_dependencies (task_id, node_id, depends_on_node_id)
                            VALUES (%s::uuid, %s::uuid, %s::uuid)
                            """,
                            (task_id, node_rows[node.id], node_rows[dep]),
                        )

                ready_keys = ready_node_ids(
                    plan.nodes,
                    completed=set(),
                    pending={n.id for n in plan.nodes},
                )
                for key in ready_keys:
                    conn.execute(
                        """
                        UPDATE task_nodes
                        SET status = 'ready', updated_at = %s
                        WHERE id = %s::uuid
                        """,
                        (now, node_rows[key]),
                    )
                    self._append_event(
                        conn,
                        task_id,
                        node_rows[key],
                        "task.node.ready",
                        f"Node {key} ready",
                        {"node_key": key, "skill": skill_by_key[key]},
                    )

                status = "running" if ready_keys else "planning"
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = %s, progress = %s, updated_at = %s
                    WHERE id = %s::uuid
                    """,
                    (status, 5 if ready_keys else 0, now, task_id),
                )
                self._append_event(
                    conn,
                    task_id,
                    None,
                    "task.running" if ready_keys else "task.planned",
                    f"Ready nodes: {', '.join(ready_keys) or '(none)'}",
                    {"ready_nodes": ready_keys},
                )

                nodes = self._list_nodes(conn, task_id)
                ready_jobs = [
                    {
                        "task_id": task_id,
                        "node_id": node_rows[key],
                        "node_key": key,
                        "skill": skill_by_key[key],
                        "attempt": 1,
                    }
                    for key in ready_keys
                ]

        return ScheduleResult(
            task_id=task_id,
            status=status,
            ready_nodes=ready_keys,
            nodes=nodes,
            ready_jobs=ready_jobs,
        )

    def get_node(self, task_id: str, node_key: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT id::text AS node_id, node_key, skill, status, attempt, max_retry,
                       assigned_agent_id::text AS agent_id, input_json, output_json,
                       error_message
                FROM task_nodes
                WHERE task_id = %s::uuid AND node_key = %s
                """,
                (task_id, node_key),
            ).fetchone()
            return dict(row) if row else None

    def get_task_goal(self, task_id: str) -> str:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                "SELECT input_json FROM tasks WHERE id = %s::uuid",
                (task_id,),
            ).fetchone()
            if not row:
                return ""
            data = row["input_json"] or {}
            if isinstance(data, str):
                data = json.loads(data)
            return str(data.get("content") or "")

    def reclaim_stale_nodes(self, *, stale_seconds: float = 900) -> list[dict[str, Any]]:
        """Mark long-running nodes as retrying and return re-enqueue jobs (长任务回收)."""
        stale_seconds = max(60.0, float(stale_seconds))
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                now = _utc_now()
                rows = conn.execute(
                    """
                    SELECT id::text AS node_id, task_id::text AS task_id, node_key, skill,
                           attempt, max_retry, assigned_agent_id::text AS agent_id
                    FROM task_nodes
                    WHERE status = 'running'
                      AND COALESCE(started_at, updated_at) < (%s - (%s || ' seconds')::interval)
                    ORDER BY updated_at ASC
                    LIMIT 20
                    """,
                    (now, str(int(stale_seconds))),
                ).fetchall()
                jobs: list[dict[str, Any]] = []
                for row in rows:
                    attempt = int(row["attempt"] or 1)
                    max_retry = int(row["max_retry"] or 3)
                    next_attempt = attempt + 1
                    if next_attempt > max_retry:
                        conn.execute(
                            """
                            UPDATE task_nodes
                            SET status = 'failed',
                                error_message = %s,
                                finished_at = %s,
                                updated_at = %s
                            WHERE id = %s::uuid
                            """,
                            (
                                f"stale running > {int(stale_seconds)}s",
                                now,
                                now,
                                row["node_id"],
                            ),
                        )
                        conn.execute(
                            """
                            UPDATE tasks
                            SET status = 'failed',
                                error_message = %s,
                                updated_at = %s,
                                finished_at = %s
                            WHERE id = %s::uuid
                            """,
                            (
                                f"node {row['node_key']} stale timeout",
                                now,
                                now,
                                row["task_id"],
                            ),
                        )
                        self._append_event(
                            conn,
                            row["task_id"],
                            row["node_id"],
                            "task.node.stale_failed",
                            f"Node {row['node_key']} failed after stale timeout",
                            {"stale_seconds": stale_seconds},
                        )
                        continue

                    conn.execute(
                        """
                        UPDATE task_nodes
                        SET status = 'retrying',
                            attempt = %s,
                            error_message = %s,
                            updated_at = %s
                        WHERE id = %s::uuid
                        """,
                        (
                            attempt,
                            f"reclaimed stale running > {int(stale_seconds)}s",
                            now,
                            row["node_id"],
                        ),
                    )
                    self._append_event(
                        conn,
                        row["task_id"],
                        row["node_id"],
                        "task.node.stale_reclaimed",
                        f"Node {row['node_key']} reclaimed after {int(stale_seconds)}s",
                        {"next_attempt": next_attempt, "stale_seconds": stale_seconds},
                    )
                    jobs.append(
                        {
                            "task_id": row["task_id"],
                            "node_id": row["node_id"],
                            "node_key": row["node_key"],
                            "skill": row["skill"],
                            "attempt": next_attempt,
                            "exclude_agent_ids": [row["agent_id"]] if row.get("agent_id") else [],
                        }
                    )
                return jobs

    def claim_running(self, task_id: str, node_key: str, agent_id: str, attempt: int) -> bool:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                now = _utc_now()
                cur = conn.execute(
                    """
                    UPDATE task_nodes
                    SET status = 'running',
                        assigned_agent_id = %s::uuid,
                        attempt = %s,
                        started_at = COALESCE(started_at, %s),
                        updated_at = %s,
                        error_message = NULL
                    WHERE task_id = %s::uuid
                      AND node_key = %s
                      AND status IN ('ready', 'retrying')
                    RETURNING id::text
                    """,
                    (agent_id, attempt, now, now, task_id, node_key),
                )
                row = cur.fetchone()
                if not row:
                    return False
                self._append_event(
                    conn,
                    task_id,
                    row["id"],
                    "agent.task.started",
                    f"Node {node_key} running on agent {agent_id}",
                    {"node_key": node_key, "agent_id": agent_id, "attempt": attempt},
                )
                conn.execute(
                    """
                    UPDATE tasks SET status = 'running', updated_at = %s
                    WHERE id = %s::uuid AND status IN ('ready', 'planning', 'running')
                    """,
                    (now, task_id),
                )
                return True

    def mark_success(
        self,
        task_id: str,
        node_key: str,
        *,
        output: dict[str, Any],
        a2a_task_id: str | None = None,
        latency_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Mark node success (or HITL wait), unlock dependents. Returns newly ready jobs."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                plan = self._load_plan(conn, task_id)
                now = _utc_now()
                plan_node = next((n for n in plan.nodes if n.id == node_key), None)
                needs_hitl = bool(plan_node and plan_node.requires_approval)
                target_status = "waiting_for_user" if needs_hitl else "success"

                node = conn.execute(
                    """
                    UPDATE task_nodes
                    SET status = %s,
                        output_json = %s::jsonb,
                        finished_at = %s,
                        updated_at = %s
                    WHERE task_id = %s::uuid AND node_key = %s
                      AND status IN ('ready', 'running', 'retrying')
                    RETURNING id::text AS node_id, skill, assigned_agent_id::text AS agent_id, attempt
                    """,
                    (target_status, Jsonb(output), now, now, task_id, node_key),
                ).fetchone()
                if not node:
                    return []

                self._append_event(
                    conn,
                    task_id,
                    node["node_id"],
                    "task.node.completed" if not needs_hitl else "task.node.awaiting_approval",
                    (
                        f"Node {node_key} completed"
                        if not needs_hitl
                        else f"Node {node_key} awaiting human approval"
                    ),
                    {"node_key": node_key, "a2a_task_id": a2a_task_id, "latency_ms": latency_ms},
                )

                # agent_runs audit (HITL still counts as successful agent execution)
                if node.get("agent_id"):
                    conn.execute(
                        """
                        INSERT INTO agent_runs (
                          tenant_id, task_id, node_id, agent_id, a2a_task_id, status,
                          response_json, latency_ms, created_at, finished_at
                        ) VALUES (
                          %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, 'success',
                          %s::jsonb, %s, %s, %s
                        )
                        """,
                        (
                            self.tenant_id,
                            task_id,
                            node["node_id"],
                            node["agent_id"],
                            a2a_task_id,
                            Jsonb(output),
                            latency_ms,
                            now,
                            now,
                        ),
                    )

                if needs_hitl:
                    rows = self._list_nodes(conn, task_id)
                    completed = {r["id"] for r in rows if r["status"] == "success"}
                    total = len(rows) or 1
                    progress = int(len(completed) * 100 / total)
                    conn.execute(
                        """
                        UPDATE tasks SET status = 'waiting_for_user', progress = %s, updated_at = %s
                        WHERE id = %s::uuid
                        """,
                        (progress, now, task_id),
                    )
                    self._append_event(
                        conn,
                        task_id,
                        node["node_id"],
                        "task.waiting_for_user",
                        f"Task paused for approval at {node_key}",
                        {"node_key": node_key, "skill": node.get("skill")},
                    )
                    return []

                return self._unlock_dependents(conn, task_id, plan, now)

    def mark_failure(
        self,
        task_id: str,
        node_key: str,
        *,
        error: str,
        attempt: int,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        """Return decision: retry | failed, plus next_attempt / max_retry."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                now = _utc_now()
                row = conn.execute(
                    """
                    SELECT id::text AS node_id, max_retry
                    FROM task_nodes
                    WHERE task_id = %s::uuid AND node_key = %s
                    """,
                    (task_id, node_key),
                ).fetchone()
                if not row:
                    return {"decision": "failed", "attempt": attempt, "max_retry": 0}

                max_retry = int(row["max_retry"] or 3)
                if attempt < max_retry:
                    conn.execute(
                        """
                        UPDATE task_nodes
                        SET status = 'retrying',
                            attempt = %s,
                            error_message = %s,
                            updated_at = %s
                        WHERE id = %s::uuid
                        """,
                        (attempt, error, now, row["node_id"]),
                    )
                    self._append_event(
                        conn,
                        task_id,
                        row["node_id"],
                        "task.node.retrying",
                        f"Node {node_key} retry {attempt}/{max_retry}: {error}",
                        {"attempt": attempt, "max_retry": max_retry, "agent_id": agent_id},
                    )
                    return {
                        "decision": "retry",
                        "attempt": attempt,
                        "next_attempt": attempt + 1,
                        "max_retry": max_retry,
                        "node_id": row["node_id"],
                    }

                conn.execute(
                    """
                    UPDATE task_nodes
                    SET status = 'failed',
                        attempt = %s,
                        error_message = %s,
                        finished_at = %s,
                        updated_at = %s
                    WHERE id = %s::uuid
                    """,
                    (attempt, error, now, now, row["node_id"]),
                )
                self._append_event(
                    conn,
                    task_id,
                    row["node_id"],
                    "task.node.failed",
                    f"Node {node_key} failed: {error}",
                    {"attempt": attempt, "agent_id": agent_id},
                )
                if agent_id:
                    conn.execute(
                        """
                        INSERT INTO agent_runs (
                          tenant_id, task_id, node_id, agent_id, status,
                          error_message, created_at, finished_at
                        ) VALUES (
                          %s::uuid, %s::uuid, %s::uuid, %s::uuid, 'failed',
                          %s, %s, %s
                        )
                        """,
                        (
                            self.tenant_id,
                            task_id,
                            row["node_id"],
                            agent_id,
                            error,
                            now,
                            now,
                        ),
                    )
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed', error_message = %s, updated_at = %s, finished_at = %s
                    WHERE id = %s::uuid
                    """,
                    (f"node {node_key} failed: {error}", now, now, task_id),
                )
                self._append_event(
                    conn,
                    task_id,
                    None,
                    "task.failed",
                    f"Task failed at node {node_key}",
                    {"node_key": node_key},
                )
                return {
                    "decision": "failed",
                    "attempt": attempt,
                    "max_retry": max_retry,
                    "node_id": row["node_id"],
                }

    def approve_node(
        self,
        task_id: str,
        node_key: str | None = None,
    ) -> dict[str, Any]:
        """Approve a waiting_for_user node and unlock dependents."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                now = _utc_now()
                if node_key:
                    node = conn.execute(
                        """
                        SELECT id::text AS node_id, node_key, skill, status
                        FROM task_nodes
                        WHERE task_id = %s::uuid AND node_key = %s
                        """,
                        (task_id, node_key),
                    ).fetchone()
                else:
                    node = conn.execute(
                        """
                        SELECT id::text AS node_id, node_key, skill, status
                        FROM task_nodes
                        WHERE task_id = %s::uuid AND status = 'waiting_for_user'
                        ORDER BY updated_at ASC
                        LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()
                if not node:
                    raise ValueError("no waiting_for_user node to approve")
                if node["status"] != "waiting_for_user":
                    raise ValueError(f"node status={node['status']} is not waiting_for_user")

                conn.execute(
                    """
                    UPDATE task_nodes
                    SET status = 'success', updated_at = %s,
                        finished_at = COALESCE(finished_at, %s)
                    WHERE id = %s::uuid
                    """,
                    (now, now, node["node_id"]),
                )
                self._append_event(
                    conn,
                    task_id,
                    node["node_id"],
                    "task.node.approved",
                    f"Node {node['node_key']} approved",
                    {"node_key": node["node_key"]},
                )
                plan = self._load_plan(conn, task_id)
                ready_jobs = self._unlock_dependents(conn, task_id, plan, now)
                return {
                    "task_id": task_id,
                    "node_key": node["node_key"],
                    "approved": True,
                    "ready_jobs": ready_jobs,
                    "status": self._task_status(conn, task_id),
                }

    def reject_node(
        self,
        task_id: str,
        *,
        node_key: str | None = None,
        reason: str = "rejected by user",
    ) -> dict[str, Any]:
        """Reject a waiting_for_user node and fail the task."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                now = _utc_now()
                if node_key:
                    node = conn.execute(
                        """
                        SELECT id::text AS node_id, node_key, status
                        FROM task_nodes
                        WHERE task_id = %s::uuid AND node_key = %s
                        """,
                        (task_id, node_key),
                    ).fetchone()
                else:
                    node = conn.execute(
                        """
                        SELECT id::text AS node_id, node_key, status
                        FROM task_nodes
                        WHERE task_id = %s::uuid AND status = 'waiting_for_user'
                        ORDER BY updated_at ASC
                        LIMIT 1
                        """,
                        (task_id,),
                    ).fetchone()
                if not node:
                    raise ValueError("no waiting_for_user node to reject")
                if node["status"] != "waiting_for_user":
                    raise ValueError(f"node status={node['status']} is not waiting_for_user")

                conn.execute(
                    """
                    UPDATE task_nodes
                    SET status = 'failed', error_message = %s,
                        finished_at = %s, updated_at = %s
                    WHERE id = %s::uuid
                    """,
                    (reason, now, now, node["node_id"]),
                )
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'failed', error_message = %s,
                        updated_at = %s, finished_at = %s
                    WHERE id = %s::uuid
                    """,
                    (f"node {node['node_key']} rejected: {reason}", now, now, task_id),
                )
                self._append_event(
                    conn,
                    task_id,
                    node["node_id"],
                    "task.node.rejected",
                    f"Node {node['node_key']} rejected",
                    {"node_key": node["node_key"], "reason": reason},
                )
                self._append_event(
                    conn,
                    task_id,
                    None,
                    "task.failed",
                    "Task failed after HITL reject",
                    {"node_key": node["node_key"]},
                )
                return {
                    "task_id": task_id,
                    "node_key": node["node_key"],
                    "rejected": True,
                    "status": "failed",
                }

    def _unlock_dependents(
        self,
        conn: Any,
        task_id: str,
        plan: TaskPlan,
        now: datetime,
    ) -> list[dict[str, Any]]:
        rows = self._list_nodes(conn, task_id)
        completed = {r["id"] for r in rows if r["status"] == "success"}
        pending = {r["id"] for r in rows if r["status"] == "pending"}
        newly = ready_node_ids(plan.nodes, completed=completed, pending=pending)
        skill_by_key = {n.id: n.skill for n in plan.nodes}
        ready_jobs: list[dict[str, Any]] = []
        for key in newly:
            updated = conn.execute(
                """
                UPDATE task_nodes
                SET status = 'ready', updated_at = %s
                WHERE task_id = %s::uuid AND node_key = %s AND status = 'pending'
                RETURNING id::text AS node_id
                """,
                (now, task_id, key),
            ).fetchone()
            if not updated:
                continue
            self._append_event(
                conn,
                task_id,
                updated["node_id"],
                "task.node.ready",
                f"Node {key} ready",
                {"node_key": key, "skill": skill_by_key[key]},
            )
            ready_jobs.append(
                {
                    "task_id": task_id,
                    "node_id": updated["node_id"],
                    "node_key": key,
                    "skill": skill_by_key[key],
                    "attempt": 1,
                }
            )

        total = len(rows) or 1
        done = len(completed)
        progress = int(done * 100 / total)
        status = "completed" if done == total else "running"
        conn.execute(
            """
            UPDATE tasks SET status = %s, progress = %s, updated_at = %s,
              finished_at = CASE WHEN %s = 'completed' THEN %s ELSE finished_at END
            WHERE id = %s::uuid
            """,
            (status, progress, now, status, now, task_id),
        )
        if status == "completed":
            self._append_event(
                conn,
                task_id,
                None,
                "task.completed",
                "Task Completed",
                {"progress": 100},
            )
        return ready_jobs

    def _task_status(self, conn: Any, task_id: str) -> str:
        row = conn.execute(
            "SELECT status FROM tasks WHERE id = %s::uuid",
            (task_id,),
        ).fetchone()
        return str(row["status"]) if row else "unknown"

    def advance_after_success(self, task_id: str, node_key: str) -> list[str]:
        """Deprecated compatibility wrapper."""
        jobs = self.mark_success(task_id, node_key, output={})
        return [j["node_key"] for j in jobs]

    def list_tasks(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 200))
        tid = tenant_id or self.tenant_id
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            if status:
                rows = conn.execute(
                    """
                    SELECT id::text AS task_id, title, status, progress,
                           created_at, updated_at, finished_at
                    FROM tasks
                    WHERE tenant_id = %s::uuid AND status = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (tid, status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id::text AS task_id, title, status, progress,
                           created_at, updated_at, finished_at
                    FROM tasks
                    WHERE tenant_id = %s::uuid
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (tid, limit),
                ).fetchall()
        return [dict(r) for r in rows]

    def get_task(self, task_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            if tenant_id:
                row = conn.execute(
                    """
                    SELECT id::text AS task_id, title, status, progress, input_json, plan_json,
                           result_json, error_message, created_at, updated_at, started_at, finished_at,
                           tenant_id::text AS tenant_id
                    FROM tasks WHERE id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (task_id, tenant_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id::text AS task_id, title, status, progress, input_json, plan_json,
                           result_json, error_message, created_at, updated_at, started_at, finished_at,
                           tenant_id::text AS tenant_id
                    FROM tasks WHERE id = %s::uuid
                    """,
                    (task_id,),
                ).fetchone()
            if not row:
                return None
            nodes = self._list_nodes(conn, task_id)
            return {**dict(row), "nodes": nodes}

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            with conn.transaction():
                row = conn.execute(
                    "SELECT id::text AS task_id, status FROM tasks WHERE id = %s::uuid FOR UPDATE",
                    (task_id,),
                ).fetchone()
                if not row:
                    return None
                if row["status"] in ("completed", "failed", "cancelled"):
                    nodes = self._list_nodes(conn, task_id)
                    return {**dict(row), "nodes": nodes, "cancelled": False}
                now = _utc_now()
                conn.execute(
                    """
                    UPDATE tasks
                    SET status = 'cancelled', updated_at = %s, finished_at = %s,
                        error_message = COALESCE(error_message, 'cancelled by user')
                    WHERE id = %s::uuid
                    """,
                    (now, now, task_id),
                )
                conn.execute(
                    """
                    UPDATE task_nodes
                    SET status = 'cancelled', updated_at = %s, finished_at = COALESCE(finished_at, %s)
                    WHERE task_id = %s::uuid
                      AND status IN ('pending', 'ready', 'running', 'retrying')
                    """,
                    (now, now, task_id),
                )
                self._append_event(
                    conn,
                    task_id,
                    None,
                    "task.cancelled",
                    "task cancelled",
                    {},
                )
                nodes = self._list_nodes(conn, task_id)
                return {
                    "task_id": task_id,
                    "status": "cancelled",
                    "cancelled": True,
                    "nodes": nodes,
                }

    def overview_stats(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        tid = tenant_id or self.tenant_id
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            totals = conn.execute(
                """
                SELECT
                  COUNT(*)::int AS total_tasks,
                  COUNT(*) FILTER (WHERE status IN ('running', 'ready', 'created', 'planned'))::int AS running,
                  COUNT(*) FILTER (WHERE status = 'completed')::int AS completed,
                  COUNT(*) FILTER (WHERE status = 'failed')::int AS failed
                FROM tasks
                WHERE tenant_id = %s::uuid
                """,
                (tid,),
            ).fetchone()
            queue = conn.execute(
                """
                SELECT COUNT(*)::int AS waiting
                FROM task_nodes n
                JOIN tasks t ON t.id = n.task_id
                WHERE n.status = 'ready' AND t.tenant_id = %s::uuid
                """,
                (tid,),
            ).fetchone()
            agents = conn.execute(
                """
                SELECT
                  COUNT(*)::int AS total,
                  COUNT(*) FILTER (WHERE status IN ('online', 'running'))::int AS online,
                  COUNT(*) FILTER (WHERE status = 'degraded')::int AS degraded,
                  COUNT(*) FILTER (WHERE status IN ('offline', 'disabled', 'unhealthy'))::int AS offline
                FROM agents
                WHERE tenant_id = %s::uuid OR tenant_id IS NULL
                """,
                (tid,),
            ).fetchone()
            trend_rows = conn.execute(
                """
                SELECT to_char(created_at::date, 'YYYY-MM-DD') AS day,
                       COUNT(*)::int AS count
                FROM tasks
                WHERE tenant_id = %s::uuid
                  AND created_at >= (CURRENT_DATE - INTERVAL '6 days')
                GROUP BY created_at::date
                ORDER BY created_at::date ASC
                """,
                (tid,),
            ).fetchall()

        total = int(totals["total_tasks"] or 0)
        completed = int(totals["completed"] or 0)
        failed = int(totals["failed"] or 0)
        finished = completed + failed
        success_rate = round((completed / finished) * 100, 1) if finished else 0.0

        # Fill missing days in last 7 days
        from datetime import date, timedelta

        day_map = {r["day"]: int(r["count"]) for r in trend_rows}
        today = date.today()
        trend = []
        for i in range(6, -1, -1):
            d = (today - timedelta(days=i)).isoformat()
            trend.append({"day": d, "count": day_map.get(d, 0)})

        return {
            "total_tasks": total,
            "running": int(totals["running"] or 0),
            "completed": completed,
            "failed": failed,
            "success_rate": success_rate,
            "agents_online": int(agents["online"] or 0),
            "agents_degraded": int(agents["degraded"] or 0),
            "agents_offline": int(agents["offline"] or 0),
            "agents_total": int(agents["total"] or 0),
            "queue_waiting": int(queue["waiting"] or 0),
            "trend": trend,
        }

    def list_events(self, task_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT event_type, message, payload, created_at AS ts
                FROM task_events
                WHERE task_id = %s::uuid
                ORDER BY id ASC
                LIMIT %s
                """,
                (task_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def _load_plan(self, conn, task_id: str) -> TaskPlan:
        row = conn.execute(
            "SELECT plan_json FROM tasks WHERE id = %s::uuid",
            (task_id,),
        ).fetchone()
        if not row or not row["plan_json"]:
            raise ValueError(f"task plan not found: {task_id}")
        raw = row["plan_json"]
        if isinstance(raw, str):
            raw = json.loads(raw)
        return TaskPlan.from_dict(raw)

    def _list_nodes(self, conn, task_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT node_key AS id, skill, status,
                   assigned_agent_id::text AS agent_id,
                   attempt, error_message
            FROM task_nodes
            WHERE task_id = %s::uuid
            ORDER BY created_at ASC, node_key ASC
            """,
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def _append_event(
        self,
        conn,
        task_id: str,
        node_id: str | None,
        event_type: str,
        message: str,
        payload: dict[str, Any] | None,
    ) -> None:
        conn.execute(
            """
            INSERT INTO task_events (task_id, node_id, event_type, message, payload, created_at)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s::jsonb, %s)
            """,
            (
                task_id,
                node_id,
                event_type,
                message,
                Jsonb(payload or {}),
                _utc_now(),
            ),
        )

    # P36.1: Request tracking methods for idempotency (lazy import to avoid circular dependency)
    def _get_request_tracking_service(self):
        """Lazy import of request tracking service."""
        if self._request_tracking_service is None:
            try:
                from request_tracking import get_request_tracking_service
                self._request_tracking_service = get_request_tracking_service()
            except ImportError:
                self._request_tracking_service = None
        return self._request_tracking_service

    # P36.2: Outbox pattern methods for distributed transactions
    def _get_outbox_processor(self):
        """Lazy import of outbox processor."""
        if self._outbox_processor is None:
            try:
                from outbox import get_outbox_processor
                self._outbox_processor = get_outbox_processor()
            except ImportError:
                self._outbox_processor = None
        return self._outbox_processor

    def write_outbox_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        target_stream: str,
    ) -> str | None:
        """Write an outbox event for reliable message delivery."""
        processor = self._get_outbox_processor()
        if not processor:
            return None
        return processor.write_event(event_type, payload, target_stream)

    def track_a2a_request(
        self,
        idempotency_key: str,
        task_id: str,
        node_id: str,
        agent_id: str,
        request_json: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Track an A2A request for idempotency."""
        service = self._get_request_tracking_service()
        if not service:
            return None
        return service.track_request(
            idempotency_key, task_id, node_id, agent_id, request_json
        )

    def get_a2a_request(self, idempotency_key: str) -> dict[str, Any] | None:
        """Get an existing A2A request by idempotency key."""
        service = self._get_request_tracking_service()
        if not service:
            return None
        return service.get_request(idempotency_key)

    def mark_a2a_request_running(self, idempotency_key: str) -> bool:
        """Mark an A2A request as running."""
        service = self._get_request_tracking_service()
        if not service:
            return False
        return service.mark_request_running(idempotency_key)

    def mark_a2a_request_completed(
        self,
        idempotency_key: str,
        response_json: dict[str, Any],
    ) -> bool:
        """Mark an A2A request as completed."""
        service = self._get_request_tracking_service()
        if not service:
            return False
        return service.mark_request_completed(idempotency_key, response_json)

    def mark_a2a_request_failed(
        self,
        idempotency_key: str,
        error_message: str,
    ) -> bool:
        """Mark an A2A request as failed."""
        service = self._get_request_tracking_service()
        if not service:
            return False
        return service.mark_request_failed(idempotency_key, error_message)

    def is_a2a_request_completed(self, idempotency_key: str) -> bool:
        """Check if an A2A request is already completed."""
        service = self._get_request_tracking_service()
        if not service:
            return False
        return service.is_request_completed(idempotency_key)

    def get_cached_a2a_response(self, idempotency_key: str) -> dict[str, Any] | None:
        """Get cached response for a completed A2A request."""
        service = self._get_request_tracking_service()
        if not service:
            return None
        return service.get_cached_response(idempotency_key)

    def get_node_info(self, task_id: str, node_key: str) -> dict[str, Any] | None:
        """Get node information for request tracking."""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT id::text, task_id::text, node_key, skill, status
                FROM task_nodes
                WHERE task_id = %s::uuid AND node_key = %s
                """,
                (task_id, node_key),
            ).fetchone()
            return dict(row) if row else None

# Import new components after class definitions to avoid circular imports
from .job_queue import JobQueue
from .event_publisher import EventPublisher

# Make them available at module level
JobQueue = JobQueue
EventPublisher = EventPublisher
