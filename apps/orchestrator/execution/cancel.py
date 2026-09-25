"""Phase 4 — cancel fan-out along runtime graph + optional A2A tasks/cancel."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def collect_descendant_task_ids(
    edges: list[dict[str, Any]], root_task_id: str
) -> list[str]:
    """Walk parent_task_id links from runtime edges; return child task ids."""
    children: dict[str, list[str]] = {}
    for e in edges:
        parent = e.get("parent_task_id")
        tid = e.get("task_id")
        if parent and tid:
            children.setdefault(str(parent), []).append(str(tid))

    out: list[str] = []
    stack = [root_task_id]
    seen = {root_task_id}
    while stack:
        cur = stack.pop()
        for child in children.get(cur, []):
            if child in seen:
                continue
            seen.add(child)
            out.append(child)
            stack.append(child)
    return out


def cancel_fanout(
    *,
    root_task_id: str,
    execution_service: Any,
    runtime_graph: Any | None = None,
    a2a_cancel: Optional[Callable[[str, str], bool]] = None,
    agent_endpoints: Optional[dict[str, str]] = None,
    extra_a2a_targets: Optional[list[dict[str, str]]] = None,
) -> dict[str, Any]:
    """Cascade cancel: execution records + runtime-graph descendants + A2A cancel.

    ``a2a_cancel(endpoint, task_id) -> bool`` is optional; when provided and
    ``agent_endpoints[agent_id]`` is known, OS issues real ``tasks/cancel``.

    ``extra_a2a_targets`` is a list of ``{"endpoint", "task_id", "agent_id"?}``
    used for in-flight harness cancel (OS root id and/or known a2a_task_id).
    Terminal executions are skipped (via ExecutionService.cancel_tree).
    """
    child_ids: list[str] = []
    edges: list[dict[str, Any]] = []
    if runtime_graph is not None:
        try:
            edges = runtime_graph.list_edges(root_task_id)
            child_ids = collect_descendant_task_ids(edges, root_task_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("runtime graph walk failed for cancel: %s", exc)

    cascade = execution_service.cancel_tree(root_task_id, child_task_ids=child_ids)

    a2a_results = []
    seen_pairs: set[tuple[str, str]] = set()

    def _emit(endpoint: str, tid: str, agent_id: Any = None) -> None:
        key = (str(endpoint), str(tid))
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        try:
            ok = a2a_cancel(endpoint, tid)  # type: ignore[misc]
            a2a_results.append(
                {"task_id": tid, "agent_id": agent_id, "endpoint": endpoint, "ok": bool(ok)}
            )
        except Exception as exc:  # noqa: BLE001
            a2a_results.append(
                {
                    "task_id": tid,
                    "agent_id": agent_id,
                    "endpoint": endpoint,
                    "ok": False,
                    "error": str(exc),
                }
            )

    if a2a_cancel:
        if agent_endpoints:
            # Cancel non-terminal children that still have an agent endpoint
            targets = {root_task_id, *child_ids}
            by_task = {e.get("task_id"): e for e in edges if e.get("task_id")}
            skipped_ids = {s.get("task_id") for s in cascade.get("skipped") or []}
            for tid in targets:
                edge = by_task.get(tid) or {}
                agent_id = edge.get("target_agent_id")
                endpoint = agent_endpoints.get(str(agent_id)) if agent_id else None
                if not endpoint:
                    continue
                if tid in skipped_ids and any(
                    "terminal" in str(s.get("reason", ""))
                    for s in (cascade.get("skipped") or [])
                    if s.get("task_id") == tid
                ):
                    continue
                _emit(endpoint, tid, agent_id)

        for item in extra_a2a_targets or []:
            endpoint = item.get("endpoint")
            tid = item.get("task_id")
            if not endpoint or not tid:
                continue
            _emit(str(endpoint), str(tid), item.get("agent_id"))

    return {
        **cascade,
        "graph_children": child_ids,
        "a2a_cancel": a2a_results,
    }


__all__ = ["cancel_fanout", "collect_descendant_task_ids"]
