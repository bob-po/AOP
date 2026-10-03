"""Project Execution Events + runtime collaboration graph → Visual Runtime graph.

Graph and Timeline share the same event source. Animation is UI-only.
"""

from __future__ import annotations

from typing import Any

from .events import normalize_event


def _status_from_event(event_type: str) -> str | None:
    """Map event → node status. None = informational, do not regress status."""
    if event_type.endswith(".failed") or event_type.endswith(".timeout"):
        return "failed"
    if event_type.endswith(".waiting"):
        return "waiting"
    if event_type.endswith(".retrying") or event_type.endswith(".retry"):
        return "retrying"
    if event_type.endswith(".recovered"):
        return "running"
    if event_type.endswith(".completed") or event_type.endswith(".cancelled"):
        return "completed"
    if event_type.endswith(".started") or event_type.endswith(".delegated"):
        return "running"
    if event_type.endswith(".discovered") or event_type.endswith(".selected"):
        return "discovered"
    if event_type.endswith(".called"):
        return "running"
    if event_type.endswith(".created"):
        return "pending"
    # Post-completion lifecycle (aggregated / evaluated / …) must not
    # overwrite task.completed → running on the TASK / agent nodes.
    if event_type.startswith("task.") or event_type.startswith("execution."):
        return None
    return "running"


def _edge_type_from_event(event_type: str) -> str:
    if "retry" in event_type:
        return "retry"
    if "recover" in event_type:
        return "recovery"
    if "tool" in event_type:
        return "tool_call"
    if "delegat" in event_type or event_type.startswith("agent."):
        return "delegation"
    if event_type.startswith("execution.") or event_type.startswith("task."):
        return "execution"
    return "execution"


def project_timeline(events: list[dict[str, Any] | Any]) -> list[dict[str, Any]]:
    """Ordered timeline projection (same source as graph)."""
    normalized = [normalize_event(e) for e in events]
    normalized.sort(
        key=lambda e: (
            e.get("sequence") is None,
            e.get("sequence") or 0,
            str(e.get("timestamp") or ""),
        )
    )
    return normalized


def apply_event_to_graph(
    graph: dict[str, Any],
    event: dict[str, Any] | Any,
) -> dict[str, Any]:
    """Incrementally apply one normalized event onto a graph snapshot (mutates copy)."""
    nodes = {n["id"]: dict(n) for n in (graph.get("nodes") or [])}
    edges = {e["id"]: dict(e) for e in (graph.get("edges") or [])}
    ev = normalize_event(event)
    et = ev["event_type"]
    seq = ev.get("sequence")
    ts = ev.get("timestamp")
    agent_id = ev.get("agent_id")
    parent_agent_id = ev.get("parent_agent_id")
    task_id = ev.get("task_id") or ev.get("root_task_id")
    root = ev.get("root_task_id") or task_id

    # Ensure root TASK node
    task_node_id = f"task:{root}"
    if task_node_id not in nodes:
        nodes[task_node_id] = {
            "id": task_node_id,
            "type": "task",
            "label": "TASK",
            "status": "running",
            "agent_id": None,
            "execution_id": None,
            "parent_id": None,
            "metadata": {"root_task_id": root},
        }

    node_status = _status_from_event(et)
    if et.startswith("task.") and node_status is not None:
        nodes[task_node_id]["status"] = node_status
        if et == "task.completed":
            nodes[task_node_id]["status"] = "completed"
        elif et == "task.failed":
            nodes[task_node_id]["status"] = "failed"

    visit_key = None
    if agent_id:
        # Visit instance: agent + task_id (or sequence) so revisits are visible
        visit_suffix = task_id or (f"seq-{seq}" if seq is not None else ev.get("event_id"))
        visit_key = f"agent:{agent_id}:{visit_suffix}"
        # Prefer stable per-task agent node; track visit_count for revisits
        stable_id = f"agent:{agent_id}"
        existing = nodes.get(stable_id)
        if existing is None:
            nodes[stable_id] = {
                "id": stable_id,
                "type": "agent",
                "label": agent_id,
                "status": node_status or "running",
                "agent_id": agent_id,
                "execution_id": ev.get("execution_id"),
                "parent_id": f"agent:{parent_agent_id}" if parent_agent_id else task_node_id,
                "metadata": {
                    "visit_count": 1,
                    "last_task_id": task_id,
                    "correlation_id": ev.get("correlation_id"),
                    "branch_hint": visit_key,
                },
            }
        else:
            meta = dict(existing.get("metadata") or {})
            last = meta.get("last_task_id")
            if task_id and last and task_id != last:
                meta["visit_count"] = int(meta.get("visit_count") or 1) + 1
            meta["last_task_id"] = task_id or last
            meta["correlation_id"] = ev.get("correlation_id") or meta.get("correlation_id")
            existing["metadata"] = meta
            if node_status is not None:
                existing["status"] = node_status
            existing["execution_id"] = ev.get("execution_id") or existing.get("execution_id")
            nodes[stable_id] = existing

        if parent_agent_id:
            parent_stable = f"agent:{parent_agent_id}"
            if parent_stable not in nodes:
                nodes[parent_stable] = {
                    "id": parent_stable,
                    "type": "agent",
                    "label": parent_agent_id,
                    "status": "completed",
                    "agent_id": parent_agent_id,
                    "execution_id": None,
                    "parent_id": task_node_id,
                    "metadata": {"visit_count": 1},
                }
            edge_id = f"edge:{parent_agent_id}->{agent_id}:{task_id or seq or ev.get('event_id')}"
            edge_status = (
                "active"
                if node_status == "running"
                else (node_status or "completed")
            )
            edges[edge_id] = {
                "id": edge_id,
                "source": parent_stable,
                "target": f"agent:{agent_id}",
                "type": _edge_type_from_event(et),
                "status": edge_status,
                "timestamp": ts,
                "metadata": {
                    "task_id": task_id,
                    "sequence": seq,
                    "event_type": et,
                },
            }
        elif et in {"agent.started", "agent.delegated", "agent.selected", "execution.started"}:
            edge_id = f"edge:{root}->{agent_id}:root"
            if edge_id not in edges:
                edges[edge_id] = {
                    "id": edge_id,
                    "source": task_node_id,
                    "target": f"agent:{agent_id}",
                    "type": "execution",
                    "status": "active",
                    "timestamp": ts,
                    "metadata": {"sequence": seq, "event_type": et},
                }

    if et.startswith("tool.") and agent_id:
        tool_name = (ev.get("payload") or {}).get("tool") or (ev.get("payload") or {}).get("name") or "tool"
        tool_id = f"tool:{agent_id}:{tool_name}:{seq or ev.get('event_id')}"
        nodes[tool_id] = {
            "id": tool_id,
            "type": "tool",
            "label": str(tool_name),
            "status": _status_from_event(et),
            "agent_id": agent_id,
            "execution_id": ev.get("execution_id"),
            "parent_id": f"agent:{agent_id}",
            "metadata": {"event_type": et},
        }
        edge_id = f"edge:tool:{tool_id}"
        edges[edge_id] = {
            "id": edge_id,
            "source": f"agent:{agent_id}",
            "target": tool_id,
            "type": "tool_call",
            "status": _status_from_event(et),
            "timestamp": ts,
            "metadata": {"sequence": seq},
        }

    if et.endswith(".failed") or et.endswith(".timeout"):
        err_id = f"error:{task_id or ev.get('event_id')}"
        nodes[err_id] = {
            "id": err_id,
            "type": "error",
            "label": "ERROR",
            "status": "failed",
            "agent_id": agent_id,
            "execution_id": ev.get("execution_id"),
            "parent_id": f"agent:{agent_id}" if agent_id else task_node_id,
            "metadata": {
                "error": (ev.get("payload") or {}).get("error"),
                "event_type": et,
            },
        }

    max_seq = graph.get("sequence") or 0
    if seq is not None and seq > max_seq:
        max_seq = seq

    status = graph.get("status") or "running"
    if et in {"task.completed", "execution.completed"}:
        status = "completed"
    elif et in {"task.failed", "execution.failed", "execution.timeout"}:
        status = "failed"
    elif et in {"execution.cancelled"}:
        status = "cancelled"
    elif et in {"execution.waiting", "agent.waiting"}:
        status = "waiting"

    return {
        **graph,
        "task_id": root,
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "sequence": max_seq,
        "status": status,
    }


def project_visual_graph(
    *,
    task_id: str,
    events: list[dict[str, Any] | Any] | None = None,
    collaboration_graph: dict[str, Any] | None = None,
    execution_view: dict[str, Any] | None = None,
    task_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build Visual Runtime snapshot: Snapshot = events fold + collaboration edges."""
    timeline = project_timeline(events or [])
    root = task_id
    if timeline:
        root = timeline[0].get("root_task_id") or task_id
    if task_row:
        root = str(task_row.get("id") or root)

    graph: dict[str, Any] = {
        "task_id": root,
        "nodes": [
            {
                "id": f"task:{root}",
                "type": "task",
                "label": (task_row or {}).get("title") or "TASK",
                "status": _map_task_status((task_row or {}).get("status")),
                "agent_id": None,
                "execution_id": None,
                "parent_id": None,
                "metadata": {
                    "root_task_id": root,
                    "created_at": (task_row or {}).get("created_at"),
                },
            }
        ],
        "edges": [],
        "events": timeline,
        "status": _map_task_status((task_row or {}).get("status")),
        "sequence": 0,
    }

    # Seed from collaboration graph (authoritative A2A edges / revisits)
    collab = collaboration_graph or {}
    agent_nodes = [n for n in (collab.get("nodes") or []) if n.get("type") == "agent"]
    for n in agent_nodes:
        aid = str(n.get("id") or "")
        if not aid:
            continue
        nid = f"agent:{aid}" if not aid.startswith("agent:") else aid
        pure_id = aid[6:] if aid.startswith("agent:") else aid
        graph["nodes"].append(
            {
                "id": nid if nid.startswith("agent:") else f"agent:{pure_id}",
                "type": "agent",
                "label": n.get("label") or n.get("agent_key") or pure_id,
                "status": _collab_status(n),
                "agent_id": pure_id,
                "execution_id": n.get("task_id"),
                "parent_id": f"task:{root}",
                "metadata": {
                    "state": n.get("state"),
                    "active_tasks": n.get("active_tasks"),
                    "agent_key": n.get("agent_key"),
                    "skills": n.get("skills"),
                    "visit_count": n.get("visit_count") or 1,
                },
            }
        )

    for link in collab.get("links") or []:
        src = link.get("source")
        tgt = link.get("target")
        if not src or not tgt:
            continue
        src_id = f"agent:{src}" if not str(src).startswith("agent:") else str(src)
        tgt_id = f"agent:{tgt}" if not str(tgt).startswith("agent:") else str(tgt)
        # Skip non-agent mid task nodes in visual agent network (data nodes separate)
        if str(src).startswith("task:") or str(tgt).startswith("task:"):
            # Represent data/task mid-nodes
            for raw, vid in ((src, src_id), (tgt, tgt_id)):
                if str(raw).startswith("task:"):
                    did = f"data:{raw}"
                    if not any(x["id"] == did for x in graph["nodes"]):
                        graph["nodes"].append(
                            {
                                "id": did,
                                "type": "data",
                                "label": link.get("skill") or str(raw),
                                "status": link.get("status") or "completed",
                                "agent_id": None,
                                "execution_id": link.get("task_id"),
                                "parent_id": None,
                                "metadata": {"skill": link.get("skill"), "depth": link.get("depth")},
                            }
                        )
            src_id = f"data:{src}" if str(src).startswith("task:") else src_id
            tgt_id = f"data:{tgt}" if str(tgt).startswith("task:") else tgt_id
        edge_id = str(link.get("id") or f"edge:{src}->{tgt}:{link.get('task_id') or ''}")
        graph["edges"].append(
            {
                "id": edge_id,
                "source": src_id,
                "target": tgt_id,
                "type": "delegation",
                "status": link.get("status") or "completed",
                "timestamp": link.get("created_at") or link.get("timestamp"),
                "metadata": {
                    "skill": link.get("skill"),
                    "depth": link.get("depth"),
                    "task_id": link.get("task_id"),
                    "correlation_id": link.get("correlation_id"),
                },
            }
        )

    # Fold events for status / tools / errors / sequence (authoritative live state)
    # Dedupe nodes by id after seed
    by_id = {n["id"]: n for n in graph["nodes"]}
    graph["nodes"] = list(by_id.values())
    by_eid = {e["id"]: e for e in graph["edges"]}
    graph["edges"] = list(by_eid.values())

    for ev in timeline:
        graph = apply_event_to_graph(graph, ev)

    # Enrich from execution view (real state, no fabricated stats)
    if execution_view:
        execute = execution_view.get("execute") or {}
        if execute.get("state"):
            st = str(execute["state"]).lower()
            if st in {"succeeded", "success"}:
                graph["status"] = "completed"
            elif st in {"failed", "timeout", "cancelled"}:
                graph["status"] = st if st != "succeeded" else "completed"
            elif st in {"waiting", "running", "pending", "retrying"}:
                graph["status"] = st
        agent = execute.get("agent_id")
        if agent:
            nid = f"agent:{agent}"
            for n in graph["nodes"]:
                if n["id"] == nid:
                    mapped = _map_exec_state(execute.get("state"))
                    if mapped:
                        n["status"] = mapped
                    n["execution_id"] = execute.get("task_id") or n.get("execution_id")
                    meta = dict(n.get("metadata") or {})
                    meta["attempt"] = execute.get("attempt")
                    meta["branch_lineage"] = execute.get("branch_lineage")
                    meta["visited_agents"] = execute.get("visited_agents")
                    n["metadata"] = meta

    # Postgres task row is source of truth after restart / post-lifecycle events
    graph = _reconcile_with_task_row(graph, task_row)

    # Final sequence
    seqs = [e.get("sequence") for e in timeline if e.get("sequence") is not None]
    if seqs:
        graph["sequence"] = max(int(s) for s in seqs)

    graph["events"] = timeline
    return graph


def _map_exec_state(state: Any) -> str | None:
    st = str(state or "").lower()
    if st in {"succeeded", "success", "completed"}:
        return "completed"
    if st in {"failed", "error", "timeout"}:
        return "failed" if st != "timeout" else "timeout"
    if st in {"cancelled", "canceled"}:
        return "cancelled"
    if st in {"waiting"}:
        return "waiting"
    if st in {"running", "pending", "retrying"}:
        return st
    return None


_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_OPEN_AGENT = frozenset({"running", "active", "discovered", "pending", "retrying"})


def _reconcile_with_task_row(
    graph: dict[str, Any],
    task_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Clamp projected status to durable task row so refresh/history stay true."""
    if not task_row:
        return graph
    mapped = _map_task_status(task_row.get("status"))
    if not mapped:
        return graph
    graph["status"] = mapped
    root = str(task_row.get("id") or graph.get("task_id") or "")
    task_node_id = f"task:{root}"
    for n in graph.get("nodes") or []:
        if n.get("id") == task_node_id or n.get("type") == "task":
            n["status"] = mapped
        elif (
            mapped in _TERMINAL
            and n.get("type") == "agent"
            and str(n.get("status") or "").lower() in _OPEN_AGENT
        ):
            # agent.completed sometimes lacks agent_id; terminal task closes hops
            n["status"] = "completed" if mapped == "completed" else mapped
    return graph


def _map_task_status(status: Any) -> str:
    s = str(status or "pending").lower()
    if s in {"completed", "success", "succeeded"}:
        return "completed"
    if s in {"failed", "error"}:
        return "failed"
    if s in {"cancelled", "canceled"}:
        return "cancelled"
    if s in {"waiting_for_user", "waiting", "waiting_for_agent"}:
        return "waiting"
    if s in {"running", "planning", "ready"}:
        return "running"
    return s or "pending"


def _collab_status(node: dict[str, Any]) -> str:
    state = str(node.get("state") or node.get("status") or "").lower()
    if state in {"busy", "running", "working"}:
        return "running"
    if state in {"ready", "online"}:
        return "completed"
    if state in {"draining", "waiting"}:
        return "waiting"
    if state in {"offline", "failed"}:
        return "failed"
    return state or "completed"
