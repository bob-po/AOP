"""Task-scoped working memory + tenant long-term memory (Phase 20)."""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .tfidf import rank_documents

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stable_key(prefix: str, text: str) -> str:
    digest = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]
    slug = re.sub(r"[^a-zA-Z0-9_\-]+", "-", (text or "")[:40].strip()).strip("-").lower()
    return f"{prefix}:{slug or 'item'}:{digest}"


class MemoryService:
    def __init__(self, database_url: str | None = None, tenant_id: str = DEFAULT_TENANT_ID):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.tenant_id = tenant_id

    def put(
        self,
        task_id: str,
        memory_key: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        key = (memory_key or "").strip()
        if not key:
            raise ValueError("memory_key is required")
        text = (content or "").strip()
        if not text:
            raise ValueError("content is required")
        tid = tenant_id or self.tenant_id
        now = _utc_now()
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                INSERT INTO task_memories (
                  tenant_id, task_id, memory_key, content, metadata, created_at, updated_at
                ) VALUES (
                  %s::uuid, %s::uuid, %s, %s, %s::jsonb, %s, %s
                )
                ON CONFLICT (task_id, memory_key) DO UPDATE SET
                  content = EXCLUDED.content,
                  metadata = EXCLUDED.metadata,
                  updated_at = EXCLUDED.updated_at
                RETURNING id::text AS id, tenant_id::text AS tenant_id, task_id::text AS task_id,
                          memory_key, content, metadata, created_at, updated_at
                """,
                (tid, task_id, key, text, Jsonb(metadata or {}), now, now),
            ).fetchone()
            conn.commit()
        return dict(row) if row else {}

    def get(self, task_id: str, memory_key: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT id::text AS id, tenant_id::text AS tenant_id, task_id::text AS task_id,
                       memory_key, content, metadata, created_at, updated_at
                FROM task_memories
                WHERE task_id = %s::uuid AND memory_key = %s
                """,
                (task_id, memory_key),
            ).fetchone()
        return dict(row) if row else None

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT id::text AS id, tenant_id::text AS tenant_id, task_id::text AS task_id,
                       memory_key, content, metadata, created_at, updated_at
                FROM task_memories
                WHERE task_id = %s::uuid
                ORDER BY updated_at DESC
                """,
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete(self, task_id: str, memory_key: str) -> bool:
        with psycopg.connect(self.database_url) as conn:
            cur = conn.execute(
                "DELETE FROM task_memories WHERE task_id = %s::uuid AND memory_key = %s",
                (task_id, memory_key),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0

    def remember_node(
        self,
        task_id: str,
        *,
        node_key: str,
        skill: str,
        text: str,
        agent_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        snippet = (text or "").strip()
        if len(snippet) > 4000:
            snippet = snippet[:4000] + "…"
        return self.put(
            task_id,
            f"node:{node_key}",
            snippet or f"(empty output from {skill})",
            metadata={
                "kind": "node_summary",
                "node_key": node_key,
                "skill": skill,
                "agent_id": agent_id,
            },
            tenant_id=tenant_id,
        )

    def remember_goal(
        self,
        task_id: str,
        goal: str,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return self.put(
            task_id,
            "goal",
            (goal or "").strip() or "(empty goal)",
            metadata={"kind": "goal"},
            tenant_id=tenant_id,
        )

    def compose_context(self, task_id: str, *, max_entries: int = 12) -> str:
        """Flat text block for executor prompts."""
        items = self.list_for_task(task_id)
        if not items:
            return ""
        goal = next((i for i in items if i["memory_key"] == "goal"), None)
        others = [i for i in items if i["memory_key"] != "goal"][: max(0, max_entries - 1)]
        ordered = ([goal] if goal else []) + others
        lines = ["Working memory:"]
        for item in ordered:
            key = item["memory_key"]
            content = (item.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"\n### {key}\n{content}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def put_tenant(
        self,
        memory_key: str,
        content: str,
        *,
        title: str | None = None,
        source_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        key = (memory_key or "").strip()
        if not key:
            raise ValueError("memory_key is required")
        text = (content or "").strip()
        if not text:
            raise ValueError("content is required")
        tid = tenant_id or self.tenant_id
        now = _utc_now()
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                INSERT INTO tenant_memories (
                  tenant_id, memory_key, title, content, source_task_id, metadata, created_at, updated_at
                ) VALUES (
                  %s::uuid, %s, %s, %s, %s::uuid, %s::jsonb, %s, %s
                )
                ON CONFLICT (tenant_id, memory_key) DO UPDATE SET
                  title = EXCLUDED.title,
                  content = EXCLUDED.content,
                  source_task_id = COALESCE(EXCLUDED.source_task_id, tenant_memories.source_task_id),
                  metadata = EXCLUDED.metadata,
                  updated_at = EXCLUDED.updated_at
                RETURNING id::text AS id, tenant_id::text AS tenant_id, memory_key, title, content,
                          source_task_id::text AS source_task_id, metadata, created_at, updated_at
                """,
                (
                    tid,
                    key,
                    (title or "").strip() or None,
                    text,
                    source_task_id,
                    Jsonb(metadata or {}),
                    now,
                    now,
                ),
            ).fetchone()
            conn.commit()
        return dict(row) if row else {}

    def list_tenant(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        tid = tenant_id or self.tenant_id
        lim = max(1, min(int(limit), 200))
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT id::text AS id, tenant_id::text AS tenant_id, memory_key, title, content,
                       source_task_id::text AS source_task_id, metadata, created_at, updated_at
                FROM tenant_memories
                WHERE tenant_id = %s::uuid
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (tid, lim),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_tenant(self, memory_key: str, *, tenant_id: str | None = None) -> bool:
        tid = tenant_id or self.tenant_id
        with psycopg.connect(self.database_url) as conn:
            cur = conn.execute(
                "DELETE FROM tenant_memories WHERE tenant_id = %s::uuid AND memory_key = %s",
                (tid, memory_key),
            )
            conn.commit()
            return (cur.rowcount or 0) > 0

    def search_tenant(
        self,
        query: str,
        *,
        tenant_id: str | None = None,
        top_k: int = 5,
        limit_corpus: int = 200,
    ) -> list[dict[str, Any]]:
        corpus = self.list_tenant(tenant_id=tenant_id, limit=limit_corpus)
        ranked = rank_documents(query, corpus, top_k=top_k)
        out: list[dict[str, Any]] = []
        for score, doc in ranked:
            item = dict(doc)
            item["score"] = round(float(score), 4)
            out.append(item)
        return out

    def recall_into_task(
        self,
        task_id: str,
        query: str,
        *,
        tenant_id: str | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        hits = self.search_tenant(query, tenant_id=tenant_id, top_k=top_k)
        if not hits:
            return []
        lines = []
        for i, h in enumerate(hits, 1):
            title = h.get("title") or h.get("memory_key")
            lines.append(
                f"{i}. [{title}] (score={h.get('score')})\n{(h.get('content') or '')[:800]}"
            )
        blob = "\n\n".join(lines)
        self.put(
            task_id,
            "recalled",
            blob,
            metadata={
                "kind": "tenant_recall",
                "query": query[:200],
                "hit_keys": [h.get("memory_key") for h in hits],
                "scores": [h.get("score") for h in hits],
            },
            tenant_id=tenant_id,
        )
        return hits

    def promote_task(
        self,
        task_id: str,
        *,
        tenant_id: str | None = None,
        max_nodes: int = 4,
    ) -> list[dict[str, Any]]:
        items = self.list_for_task(task_id)
        if not items:
            return []
        tid = tenant_id or self.tenant_id
        written: list[dict[str, Any]] = []
        goal = next((i for i in items if i["memory_key"] == "goal"), None)
        if goal and (goal.get("content") or "").strip():
            content = (goal["content"] or "").strip()
            written.append(
                self.put_tenant(
                    _stable_key("goal", content),
                    content[:2000],
                    title=(content[:60] + "…") if len(content) > 60 else content,
                    source_task_id=task_id,
                    metadata={"kind": "promoted_goal", "task_id": task_id},
                    tenant_id=tid,
                )
            )
        nodes = [i for i in items if str(i.get("memory_key") or "").startswith("node:")]
        for item in nodes[:max_nodes]:
            content = (item.get("content") or "").strip()
            if len(content) < 20:
                continue
            key = _stable_key(str(item["memory_key"]), content)
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            written.append(
                self.put_tenant(
                    key,
                    content[:2000],
                    title=str(item["memory_key"]),
                    source_task_id=task_id,
                    metadata={
                        "kind": "promoted_node",
                        "task_id": task_id,
                        "node_key": meta.get("node_key"),
                        "skill": meta.get("skill"),
                    },
                    tenant_id=tid,
                )
            )
        return written
