"""A2A OS: runtime execution graph.

Records the Agent-to-Agent call edges that emerge at runtime when Agents
autonomously discover and invoke one another, and reconstructs the call graph
for a given ``root_task_id``.

IMPORTANT: this is a *runtime execution graph*, not a predefined workflow DAG.
Edges are appended as calls actually happen; nothing here declares in advance
that Agent A must call Agent B.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from db import connect

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RuntimeGraphService:
    """Persist and query the runtime Agent-to-Agent execution graph."""

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

    def record_edge(
        self,
        *,
        caller_agent_id: str,
        target_agent_id: str,
        root_task_id: str | None = None,
        parent_task_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
        skill: str | None = None,
        depth: int = 0,
        status: str = "submitted",
        tenant_id: str | None = None,
        delegation_id: str | None = None,
        attempt: int = 1,
        error: str | None = None,
    ) -> dict[str, Any]:
        sql = """
            INSERT INTO a2a_runtime_edges (
              root_task_id, parent_task_id, task_id, correlation_id,
              caller_agent_id, target_agent_id, skill, depth, status, tenant_id,
              delegation_id, attempt, started_at, error, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, now())
            RETURNING id, root_task_id, parent_task_id, task_id, correlation_id,
                      caller_agent_id, target_agent_id, skill, depth, status,
                      tenant_id, delegation_id, attempt, started_at, finished_at,
                      duration_ms, error, created_at
        """
        params = (
            root_task_id,
            parent_task_id,
            task_id,
            correlation_id,
            caller_agent_id,
            target_agent_id,
            skill,
            int(depth or 0),
            status,
            tenant_id or self.tenant_id,
            delegation_id,
            int(attempt or 1),
            error,
        )
        with connect(self.database_url) as conn:
            row = conn.execute(sql, params).fetchone()
        return self._serialize(row)

    def update_edge_status(
        self,
        *,
        task_id: str | None = None,
        delegation_id: str | None = None,
        status: str,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        """Mark a runtime edge finished (Phase 3 live collaboration graph)."""
        if not task_id and not delegation_id:
            return None
        clauses = []
        params: list[Any] = []
        if task_id:
            clauses.append("task_id = %s")
            params.append(task_id)
        if delegation_id:
            clauses.append("delegation_id = %s")
            params.append(delegation_id)
        where = " AND ".join(clauses)
        sql = f"""
            UPDATE a2a_runtime_edges
               SET status = %s,
                   error = COALESCE(%s, error),
                   finished_at = now(),
                   duration_ms = CASE
                     WHEN started_at IS NOT NULL
                     THEN EXTRACT(EPOCH FROM (now() - started_at)) * 1000
                     ELSE duration_ms END,
                   updated_at = now()
             WHERE {where}
         RETURNING id, root_task_id, parent_task_id, task_id, correlation_id,
                   caller_agent_id, target_agent_id, skill, depth, status,
                   tenant_id, delegation_id, attempt, started_at, finished_at,
                   duration_ms, error, created_at
        """
        with connect(self.database_url) as conn:
            row = conn.execute(sql, [status, error, *params]).fetchone()
        return self._serialize(row) if row else None

    def list_edges(self, root_task_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
        sql = """
            SELECT id, root_task_id, parent_task_id, task_id, correlation_id,
                   caller_agent_id, target_agent_id, skill, depth, status,
                   tenant_id, created_at
            FROM a2a_runtime_edges
            WHERE root_task_id = %s
            ORDER BY id ASC
            LIMIT %s
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (root_task_id, max(1, min(limit, 2000)))).fetchall()
        return [self._serialize(r) for r in rows]

    def branch_lineage(self, root_task_id: str, task_id: str | None) -> dict[str, Any]:
        """Authoritative lineage for one branch, rebuilt from recorded edges.

        Walks ``parent_task_id`` links from ``task_id`` up to the root and returns
        the ordered chain of agents that handled this branch (matching
        ``CallContext.visited_agents``), the real depth, and per-agent visit
        counts. Limited revisits are countable (A→B→A → visits[A]=2); the OS
        uses this instead of trusting caller-supplied ``visited_agents``
        (anti-tamper, Phase 2).
        """
        edges = self.list_edges(root_task_id)
        by_task: dict[str, dict[str, Any]] = {}
        for e in edges:
            tid = e.get("task_id")
            if tid:
                by_task.setdefault(tid, e)

        # Walk leaf → root collecting handlers (edge targets). Reverse to get
        # root → leaf, then prepend the topmost caller so the chain mirrors
        # CallContext: [A, B, A] for a legal reverse call.
        handlers_rev: list[str] = []
        seen_tasks: set[str] = set()
        cursor = task_id
        depth = 0
        top_caller: str | None = None
        while cursor and cursor in by_task and cursor not in seen_tasks:
            seen_tasks.add(cursor)
            e = by_task[cursor]
            target = e.get("target_agent_id")
            if target:
                handlers_rev.append(str(target))
            depth = max(depth, int(e.get("depth") or 0))
            top_caller = str(e.get("caller_agent_id") or "") or top_caller
            cursor = e.get("parent_task_id")
        handlers_rev.reverse()
        if top_caller and (not handlers_rev or handlers_rev[0] != top_caller):
            chain = [top_caller] + handlers_rev
        else:
            chain = handlers_rev

        visits: dict[str, int] = {}
        for a in chain:
            visits[a] = visits.get(a, 0) + 1
        return {
            "root_task_id": root_task_id,
            "task_id": task_id,
            "agent_chain": chain,
            "depth": depth,
            "agent_visits": visits,
        }

    def collaboration_graph(self, root_task_id: str) -> dict[str, Any]:
        """Frontend-friendly collaboration graph (nodes + links + tree).

        Stabilizes the runtime execution graph into a schema suitable for
        React Flow / D3 without changing the underlying edge store.
        """
        base = self.get_graph(root_task_id)
        edges = base.get("edges") or []
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        seen_agents: set[str] = set()
        for e in edges:
            for role, key in (("caller", "caller_agent_id"), ("target", "target_agent_id")):
                aid = e.get(key)
                if aid and aid not in seen_agents:
                    seen_agents.add(str(aid))
                    nodes.append({
                        "id": str(aid),
                        "type": "agent",
                        "label": str(aid),
                        "role": role,
                    })
            tid = e.get("task_id")
            if tid:
                nodes.append({
                    "id": f"task:{tid}",
                    "type": "task",
                    "label": str(tid),
                    "task_id": tid,
                    "status": e.get("status"),
                    "skill": e.get("skill"),
                    "depth": e.get("depth"),
                    "agent_id": e.get("target_agent_id"),
                })
            links.append({
                "id": f"edge:{e.get('id')}",
                "source": str(e.get("caller_agent_id") or ""),
                "target": str(e.get("target_agent_id") or ""),
                "task_id": tid,
                "parent_task_id": e.get("parent_task_id"),
                "skill": e.get("skill"),
                "depth": e.get("depth"),
                "status": e.get("status"),
                "correlation_id": e.get("correlation_id"),
                "created_at": e.get("created_at"),
            })
        return {
            "root_task_id": root_task_id,
            "kind": "collaboration_graph",
            "node_count": len(nodes),
            "link_count": len(links),
            "max_depth": base.get("max_depth", 0),
            "agents": base.get("agents") or [],
            "nodes": nodes,
            "links": links,
            "tree": base.get("tree") or [],
            "edges": edges,
        }

    def root_stats(self, root_task_id: str) -> dict[str, Any]:
        """Authoritative aggregate call stats for a root task (DB-backed)."""
        edges = self.list_edges(root_task_id)
        visits: dict[str, int] = {}
        for e in edges:
            for a in (e.get("caller_agent_id"), e.get("target_agent_id")):
                if a:
                    visits[str(a)] = visits.get(str(a), 0) + 1
        return {
            "root_task_id": root_task_id,
            "call_count": len(edges),
            "max_depth": max((int(e.get("depth") or 0) for e in edges), default=0),
            "agent_visits": visits,
        }

    def get_graph(self, root_task_id: str) -> dict[str, Any]:
        """Reconstruct the runtime execution tree for a root task."""
        edges = self.list_edges(root_task_id)
        nodes: list[dict[str, Any]] = []
        by_task: dict[str, dict[str, Any]] = {}
        for e in edges:
            node = {
                "task_id": e.get("task_id"),
                "caller_agent_id": e.get("caller_agent_id"),
                "target_agent_id": e.get("target_agent_id"),
                "skill": e.get("skill"),
                "depth": e.get("depth"),
                "status": e.get("status"),
                "correlation_id": e.get("correlation_id"),
                "created_at": e.get("created_at"),
                "children": [],
            }
            nodes.append(node)
            tid = e.get("task_id")
            if tid:
                by_task.setdefault(tid, node)

        roots: list[dict[str, Any]] = []
        for e, node in zip(edges, nodes):
            parent = e.get("parent_task_id")
            parent_node = by_task.get(parent) if parent else None
            if parent_node is not None and parent_node is not node:
                parent_node["children"].append(node)
            else:
                roots.append(node)

        agents = sorted(
            {
                a
                for e in edges
                for a in (e.get("caller_agent_id"), e.get("target_agent_id"))
                if a
            }
        )
        max_depth = max((int(e.get("depth") or 0) for e in edges), default=0)
        return {
            "root_task_id": root_task_id,
            "kind": "runtime_execution_graph",
            "edge_count": len(edges),
            "max_depth": max_depth,
            "agents": agents,
            "edges": edges,
            "tree": roots,
        }

    @staticmethod
    def _serialize(row: Any) -> dict[str, Any]:
        d = dict(row)
        created = d.get("created_at")
        if isinstance(created, datetime):
            d["created_at"] = created.isoformat()
        return d


__all__ = ["RuntimeGraphService"]
