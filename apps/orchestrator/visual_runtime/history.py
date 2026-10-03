"""Rebuild Visual Runtime timeline when in-memory EventBus is empty.

Sources (durable): collaboration links (a2a_runtime_edges) + task_events.
Does not invent agent metrics — only projects recorded edges / scheduler events.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4


def _ts(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _ts_key(value: Any) -> float:
    """Sortable epoch; missing → +inf so undated events sink."""
    raw = _ts(value)
    if not raw:
        return float("inf")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:  # noqa: BLE001
        return float("inf")


def synthesize_from_collaboration(
    *,
    root_task_id: str,
    collaboration_graph: dict[str, Any] | None,
    task_row: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a minimal ordered event list from collaboration links + task row."""
    events: list[dict[str, Any]] = []
    seq = 0

    def _push(
        event_type: str,
        *,
        agent_id: str | None = None,
        parent_agent_id: str | None = None,
        task_id: str | None = None,
        timestamp: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        nonlocal seq
        seq += 1
        events.append(
            {
                "event_id": f"synth_{uuid4().hex[:16]}",
                "event_type": event_type,
                "task_id": task_id or root_task_id,
                "root_task_id": root_task_id,
                "correlation_id": (task_row or {}).get("id") or root_task_id,
                "agent_id": agent_id,
                "parent_agent_id": parent_agent_id,
                "timestamp": timestamp or _ts((task_row or {}).get("created_at")),
                "sequence": seq,
                "payload": {
                    "sequence": seq,
                    "synthetic": True,
                    **(payload or {}),
                },
            }
        )

    created = _ts((task_row or {}).get("created_at"))
    _push("task.created", timestamp=created)

    status = str((task_row or {}).get("status") or "").lower()
    if status and status not in {"created", "pending"}:
        _push("task.started", timestamp=created)

    links = list((collaboration_graph or {}).get("links") or [])
    links.sort(
        key=lambda l: (
            l.get("depth") is None,
            int(l.get("depth") or 0),
            str(l.get("created_at") or ""),
            str(l.get("id") or ""),
        )
    )

    for link in links:
        src = link.get("source")
        tgt = link.get("target")
        if not src or not tgt:
            continue
        # Skip mid task:task hops for timeline (agent hops only)
        if str(src).startswith("task:") or str(tgt).startswith("task:"):
            continue
        ts = _ts(link.get("created_at") or link.get("timestamp")) or created
        # Keep narrative order: hops never precede task.created
        if created and _ts_key(ts) < _ts_key(created):
            ts = created
        st = str(link.get("status") or "submitted").lower()
        tid = link.get("task_id")
        skill = link.get("skill")
        _push(
            "agent.delegated",
            agent_id=str(tgt),
            parent_agent_id=str(src),
            task_id=str(tid) if tid else root_task_id,
            timestamp=ts,
            payload={"skill": skill, "status": st, "depth": link.get("depth")},
        )
        if st in {"running", "working", "submitted", "accepted"}:
            _push(
                "agent.started",
                agent_id=str(tgt),
                parent_agent_id=str(src),
                task_id=str(tid) if tid else root_task_id,
                timestamp=ts,
                payload={"skill": skill},
            )
        elif st in {"completed", "succeeded", "success"}:
            _push(
                "agent.started",
                agent_id=str(tgt),
                parent_agent_id=str(src),
                task_id=str(tid) if tid else root_task_id,
                timestamp=ts,
                payload={"skill": skill},
            )
            _push(
                "agent.completed",
                agent_id=str(tgt),
                parent_agent_id=str(src),
                task_id=str(tid) if tid else root_task_id,
                timestamp=ts,
                payload={"skill": skill},
            )
        elif st in {"failed", "error", "timeout"}:
            _push(
                "agent.failed",
                agent_id=str(tgt),
                parent_agent_id=str(src),
                task_id=str(tid) if tid else root_task_id,
                timestamp=ts,
                payload={"skill": skill, "status": st},
            )

    if status in {"completed", "success", "succeeded"}:
        _push(
            "task.completed",
            timestamp=_ts(
                (task_row or {}).get("finished_at")
                or (task_row or {}).get("updated_at")
                or (task_row or {}).get("completed_at")
            )
            or created,
        )
    elif status in {"failed", "error"}:
        _push(
            "task.failed",
            timestamp=_ts(
                (task_row or {}).get("finished_at")
                or (task_row or {}).get("updated_at")
            )
            or created,
        )
    elif status in {"cancelled", "canceled"}:
        _push(
            "execution.cancelled",
            timestamp=_ts((task_row or {}).get("updated_at")) or created,
        )

    return events


def merge_task_scheduler_events(
    *,
    root_task_id: str,
    task_events: list[dict[str, Any]] | None,
    base: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge scheduler task_events with optional agent-hop base; re-sequence by time."""
    merged: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _key(et: str, ts: str | None, agent_id: Any) -> str:
        return f"{et}|{ts or ''}|{agent_id or ''}"

    for e in base or []:
        et = str(e.get("event_type") or "")
        ts = _ts(e.get("timestamp"))
        k = _key(et, ts, e.get("agent_id"))
        if k in seen_keys:
            continue
        seen_keys.add(k)
        merged.append({**e, "timestamp": ts or e.get("timestamp")})

    for raw in task_events or []:
        et = str(raw.get("event_type") or "task.event")
        visual = et
        if et in {"task.created", "task.started", "task.completed", "task.failed"}:
            visual = et
        elif et in {"task.running"}:
            visual = "task.started"
        elif et.endswith(".started") or et == "node.started":
            visual = "agent.started"
        elif et.endswith(".completed") or et == "node.completed" or et == "node.success":
            visual = "agent.completed"
        elif et.endswith(".failed") or et == "node.failed":
            visual = "agent.failed"
        payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
        agent_id = None
        if isinstance(payload, dict):
            agent_id = payload.get("agent_id") or payload.get("agent_key")
        ts = _ts(raw.get("ts") or raw.get("created_at"))
        k = _key(visual, ts, agent_id)
        if k in seen_keys:
            continue
        # Drop noisy planner chatter that duplicates agent hops
        if et in {"task.node.ready", "task.planned", "task.node.checkpoint"}:
            continue
        seen_keys.add(k)
        merged.append(
            {
                "event_id": f"taskevt_{uuid4().hex[:12]}",
                "event_type": visual,
                "original_event_type": et,
                "task_id": root_task_id,
                "root_task_id": root_task_id,
                "agent_id": agent_id,
                "timestamp": ts,
                "payload": {
                    "synthetic": True,
                    "message": raw.get("message"),
                    **(payload or {}),
                },
            }
        )

    # Prefer scheduler agent.started/completed over synthetic duplicates
    sched_agent_types = {
        str(e.get("event_type"))
        for e in merged
        if e.get("original_event_type")
        and str(e.get("event_type") or "") in {"agent.started", "agent.completed", "agent.failed"}
    }
    if sched_agent_types:
        merged = [
            e
            for e in merged
            if not (
                (e.get("payload") or {}).get("synthetic")
                and not e.get("original_event_type")
                and str(e.get("event_type") or "") in sched_agent_types
            )
        ]

    phase = {
        "task.created": 0,
        "task.started": 1,
        "agent.delegated": 2,
        "agent.started": 3,
        "agent.waiting": 4,
        "agent.recovered": 5,
        "agent.failed": 6,
        "agent.completed": 7,
        "task.completed": 8,
        "task.failed": 9,
        "execution.cancelled": 10,
        "task.aggregated": 11,
        "task.evaluated": 12,
    }
    # Phase-first keeps task.created ahead of same-second agent hops after restart
    merged.sort(
        key=lambda e: (
            phase.get(str(e.get("event_type") or ""), 50),
            _ts_key(e.get("timestamp")),
            str(e.get("event_type") or ""),
        )
    )
    for i, e in enumerate(merged, start=1):
        e["sequence"] = i
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        e["payload"] = {**payload, "sequence": i}
    return merged
