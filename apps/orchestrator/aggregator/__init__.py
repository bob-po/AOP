"""Aggregate completed node artifacts into task.result_json."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from db import connect
from psycopg.types.json import Jsonb


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Aggregator:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )

    def build_result(self, task_id: str) -> dict[str, Any]:
        with connect(self.database_url) as conn:
            task = conn.execute(
                """
                SELECT title, input_json, plan_json, status
                FROM tasks WHERE id = %s::uuid
                """,
                (task_id,),
            ).fetchone()
            if not task:
                raise ValueError(f"task not found: {task_id}")

            nodes = conn.execute(
                """
                SELECT node_key, skill, status, output_json, error_message,
                       assigned_agent_id::text AS agent_id
                FROM task_nodes
                WHERE task_id = %s::uuid
                ORDER BY created_at ASC, node_key ASC
                """,
                (task_id,),
            ).fetchall()

            node_results = []
            texts: list[str] = []
            all_artifacts: list[dict[str, Any]] = []
            for n in nodes:
                out = n["output_json"] or {}
                if isinstance(out, str):
                    import json

                    out = json.loads(out)
                text = None
                arts: list[dict[str, Any]] = []
                if isinstance(out, dict):
                    text = out.get("text")
                    arts = list(out.get("artifacts") or [])
                    if text:
                        texts.append(f"## {n['node_key']} ({n['skill']})\n{text}")
                    for art in arts:
                        all_artifacts.append({**art, "node_id": n["node_key"]})
                node_results.append(
                    {
                        "id": n["node_key"],
                        "skill": n["skill"],
                        "status": n["status"],
                        "agent_id": n["agent_id"],
                        "output": out,
                        "artifacts": arts,
                        "error": n["error_message"],
                    }
                )

            goal = ""
            input_json = task["input_json"] or {}
            if isinstance(input_json, dict):
                goal = str(input_json.get("content") or "")

            result = {
                "task_id": task_id,
                "title": task["title"],
                "goal": goal,
                "summary": "\n\n".join(texts) if texts else f"Task {task_id} completed",
                "artifacts": all_artifacts,
                "nodes": node_results,
                "aggregated_at": _utc_now().isoformat(),
            }

            conn.execute(
                """
                UPDATE tasks
                SET result_json = %s::jsonb, updated_at = %s
                WHERE id = %s::uuid
                """,
                (Jsonb(result), _utc_now(), task_id),
            )
            conn.execute(
                """
                INSERT INTO task_events (task_id, node_id, event_type, message, payload, created_at)
                VALUES (%s::uuid, NULL, 'task.aggregated', 'Result aggregated', %s::jsonb, %s)
                """,
                (task_id, Jsonb({"node_count": len(node_results)}), _utc_now()),
            )
            conn.commit()
            return result
