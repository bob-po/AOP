"""Task evaluation: heuristic scoring for completed / failed tasks."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


class EvaluationService:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )

    def evaluate(
        self,
        task_id: str,
        *,
        method: str = "heuristic",
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            task = conn.execute(
                """
                SELECT id::text AS task_id, tenant_id::text AS tenant_id, title, status,
                       progress, result_json, input_json, created_at, finished_at, updated_at
                FROM tasks WHERE id = %s::uuid
                """,
                (task_id,),
            ).fetchone()
            if not task:
                raise ValueError(f"task not found: {task_id}")
            tid = tenant_id or task["tenant_id"] or DEFAULT_TENANT_ID
            nodes = conn.execute(
                """
                SELECT node_key, skill, status, error_message, output_json,
                       started_at, finished_at
                FROM task_nodes WHERE task_id = %s::uuid
                """,
                (task_id,),
            ).fetchall()

            scored = self._heuristic(dict(task), [dict(n) for n in nodes])
            now = _utc_now()
            row = conn.execute(
                """
                INSERT INTO task_evaluations (
                  tenant_id, task_id, method, score, grade, dimensions, summary, details, created_at
                ) VALUES (
                  %s::uuid, %s::uuid, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s
                )
                ON CONFLICT (task_id, method) DO UPDATE SET
                  score = EXCLUDED.score,
                  grade = EXCLUDED.grade,
                  dimensions = EXCLUDED.dimensions,
                  summary = EXCLUDED.summary,
                  details = EXCLUDED.details,
                  created_at = EXCLUDED.created_at
                RETURNING id::text AS id, tenant_id::text AS tenant_id, task_id::text AS task_id,
                          method, score, grade, dimensions, summary, details, created_at
                """,
                (
                    tid,
                    task_id,
                    method,
                    scored["score"],
                    scored["grade"],
                    Jsonb(scored["dimensions"]),
                    scored["summary"],
                    Jsonb(scored["details"]),
                    now,
                ),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO task_events (task_id, node_id, event_type, message, payload, created_at)
                VALUES (%s::uuid, NULL, 'task.evaluated', %s, %s::jsonb, %s)
                """,
                (
                    task_id,
                    f"Evaluation {scored['grade']} ({scored['score']})",
                    Jsonb({"score": scored["score"], "grade": scored["grade"], "method": method}),
                    now,
                ),
            )
            conn.commit()
            return dict(row) if row else scored

    def get_for_task(self, task_id: str, *, method: str = "heuristic") -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT id::text AS id, tenant_id::text AS tenant_id, task_id::text AS task_id,
                       method, score, grade, dimensions, summary, details, created_at
                FROM task_evaluations
                WHERE task_id = %s::uuid AND method = %s
                """,
                (task_id, method),
            ).fetchone()
        return dict(row) if row else None

    def list(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 50,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 200))
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            clauses = ["1=1"]
            args: list[Any] = []
            if tenant_id:
                clauses.append("e.tenant_id = %s::uuid")
                args.append(tenant_id)
            if min_score is not None:
                clauses.append("e.score >= %s")
                args.append(min_score)
            args.append(limit)
            rows = conn.execute(
                f"""
                SELECT e.id::text AS id, e.tenant_id::text AS tenant_id, e.task_id::text AS task_id,
                       e.method, e.score, e.grade, e.dimensions, e.summary, e.details, e.created_at,
                       t.title AS task_title, t.status AS task_status
                FROM task_evaluations e
                JOIN tasks t ON t.id = e.task_id
                WHERE {' AND '.join(clauses)}
                ORDER BY e.created_at DESC
                LIMIT %s
                """,
                args,
            ).fetchall()
        return [dict(r) for r in rows]

    def overview(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            args: list[Any] = []
            where = ""
            if tenant_id:
                where = "WHERE tenant_id = %s::uuid"
                args.append(tenant_id)
            row = conn.execute(
                f"""
                SELECT COUNT(*)::int AS total,
                       COALESCE(AVG(score), 0)::float AS avg_score,
                       COUNT(*) FILTER (WHERE grade = 'A')::int AS grade_a,
                       COUNT(*) FILTER (WHERE grade = 'B')::int AS grade_b,
                       COUNT(*) FILTER (WHERE grade = 'C')::int AS grade_c,
                       COUNT(*) FILTER (WHERE grade IN ('D','F'))::int AS grade_df
                FROM task_evaluations
                {where}
                """,
                args,
            ).fetchone()
        return dict(row) if row else {}

    def _heuristic(self, task: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
        status = (task.get("status") or "").lower()
        total = len(nodes) or 1
        success = sum(1 for n in nodes if n.get("status") == "success")
        failed = sum(1 for n in nodes if n.get("status") == "failed")
        cancelled = sum(1 for n in nodes if n.get("status") == "cancelled")
        success_rate = success / total

        # base by terminal status
        if status == "completed":
            base = 55.0
        elif status == "failed":
            base = 25.0
        elif status == "cancelled":
            base = 15.0
        else:
            base = 35.0

        reliability = round(success_rate * 100, 1)
        completeness = round(success_rate * 100, 1)

        # artifacts / summary
        result = task.get("result_json") or {}
        if isinstance(result, str):
            result = json.loads(result)
        arts = result.get("artifacts") if isinstance(result, dict) else None
        art_count = len(arts) if isinstance(arts, list) else 0
        has_summary = bool(isinstance(result, dict) and (result.get("summary") or "").strip())
        artifact_score = min(100.0, 40.0 + art_count * 15.0) if art_count else (20.0 if status == "completed" else 0.0)
        if has_summary:
            artifact_score = min(100.0, artifact_score + 20.0)

        # latency: prefer finishing within 120s
        latency_score = 70.0
        created = task.get("created_at")
        finished = task.get("finished_at") or task.get("updated_at")
        duration_s = None
        if created and finished:
            try:
                duration_s = max(0.0, (finished - created).total_seconds())
                if duration_s <= 30:
                    latency_score = 100.0
                elif duration_s <= 120:
                    latency_score = 85.0
                elif duration_s <= 300:
                    latency_score = 65.0
                else:
                    latency_score = 45.0
            except Exception:  # noqa: BLE001
                duration_s = None

        score = (
            base
            + success_rate * 30.0
            + (8.0 if art_count else 0.0)
            + (5.0 if has_summary else 0.0)
            + (latency_score - 70.0) * 0.15
            - failed * 4.0
            - cancelled * 2.0
        )
        score = round(max(0.0, min(100.0, score)), 1)
        grade = _grade(score)

        dims = {
            "completeness": completeness,
            "reliability": reliability,
            "artifacts": round(artifact_score, 1),
            "latency": round(latency_score, 1),
        }
        summary = (
            f"Grade {grade} ({score}). status={status}, nodes={success}/{total} ok, "
            f"artifacts={art_count}"
            + (f", duration={int(duration_s)}s" if duration_s is not None else "")
        )
        return {
            "score": score,
            "grade": grade,
            "dimensions": dims,
            "summary": summary,
            "details": {
                "status": status,
                "nodes_total": total,
                "nodes_success": success,
                "nodes_failed": failed,
                "nodes_cancelled": cancelled,
                "artifact_count": art_count,
                "has_summary": has_summary,
                "duration_sec": duration_s,
            },
        }
