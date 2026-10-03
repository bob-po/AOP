"""Visual Runtime event vocabulary + normalization.

Preserves existing ExecutionEvent types; adds aliases for the Visual Runtime
surface without changing Execution State Machine semantics.
"""

from __future__ import annotations

from typing import Any

# Canonical Visual Runtime event types (product contract)
VISUAL_EVENT_TYPES = frozenset(
    {
        "task.created",
        "task.started",
        "task.completed",
        "task.failed",
        "agent.discovered",
        "agent.selected",
        "agent.delegated",
        "agent.started",
        "agent.waiting",
        "agent.completed",
        "agent.failed",
        "agent.retrying",
        "agent.recovered",
        "tool.called",
        "tool.completed",
        "tool.failed",
        "execution.started",
        "execution.waiting",
        "execution.completed",
        "execution.failed",
        "execution.timeout",
        "execution.retry",
        "execution.recovered",
        "execution.cancelled",
    }
)

# Existing ExecutionEvent / delegation types → Visual Runtime primary type
_EXEC_TO_VISUAL: dict[str, str] = {
    "task.created": "task.created",
    "task.started": "execution.started",
    "task.waiting": "execution.waiting",
    "task.retrying": "execution.retry",
    "task.completed": "execution.completed",
    "task.failed": "execution.failed",
    "task.timeout": "execution.timeout",
    "task.cancelled": "execution.cancelled",
    "delegation.requested": "agent.delegated",
    "delegation.accepted": "agent.delegated",
    "delegation.started": "agent.started",
    "delegation.completed": "agent.completed",
    "delegation.failed": "agent.failed",
    "delegation.released": "agent.completed",
}


def map_execution_event_type(event_type: str, *, operation: str | None = None) -> str:
    """Map an Execution Runtime event_type to Visual Runtime vocabulary."""
    et = str(event_type or "")
    if et in VISUAL_EVENT_TYPES:
        return et
    mapped = _EXEC_TO_VISUAL.get(et)
    if mapped:
        # Agent-scoped execute transitions surface as agent.* when agent_id present
        if operation == "execute" and mapped.startswith("execution."):
            agent_alias = {
                "execution.started": "agent.started",
                "execution.waiting": "agent.waiting",
                "execution.completed": "agent.completed",
                "execution.failed": "agent.failed",
                "execution.retry": "agent.retrying",
                "execution.timeout": "agent.failed",
            }.get(mapped)
            if agent_alias:
                return agent_alias
        return mapped
    return et


def normalize_event(raw: dict[str, Any] | Any) -> dict[str, Any]:
    """Normalize an ExecutionEvent (dict or dataclass) for Visual Runtime clients.

    Guarantees: event_id, event_type (visual), sequence (top-level), lineage ids.
    Does not invent agent/tool stats — only projects fields already present.
    """
    if hasattr(raw, "to_dict"):
        data = raw.to_dict()
    elif isinstance(raw, dict):
        data = dict(raw)
    else:
        data = {
            "event_type": getattr(raw, "event_type", "unknown"),
            "event_id": getattr(raw, "event_id", None),
            "timestamp": getattr(raw, "timestamp", None),
            "root_task_id": getattr(raw, "root_task_id", None),
            "correlation_id": getattr(raw, "correlation_id", None),
            "task_id": getattr(raw, "task_id", None),
            "agent_id": getattr(raw, "agent_id", None),
            "parent_task_id": getattr(raw, "parent_task_id", None),
            "payload": getattr(raw, "payload", {}) or {},
        }

    payload = dict(data.get("payload") or {})
    operation = payload.get("operation")
    original_type = str(data.get("event_type") or "")
    visual_type = map_execution_event_type(original_type, operation=operation)

    sequence = data.get("sequence")
    if sequence is None:
        sequence = payload.get("sequence")
    try:
        sequence = int(sequence) if sequence is not None else None
    except (TypeError, ValueError):
        sequence = None

    parent_agent_id = (
        data.get("parent_agent_id")
        or payload.get("parent_agent_id")
        or payload.get("caller_agent_id")
    )
    execution_id = (
        data.get("execution_id")
        or payload.get("execution_id")
        or payload.get("record_id")
        or data.get("task_id")
    )

    out = {
        "event_id": data.get("event_id"),
        "event_type": visual_type,
        "original_event_type": original_type,
        "task_id": data.get("task_id"),
        "root_task_id": data.get("root_task_id") or data.get("task_id"),
        "correlation_id": data.get("correlation_id"),
        "execution_id": execution_id,
        "agent_id": data.get("agent_id") or payload.get("agent_id"),
        "parent_agent_id": parent_agent_id,
        "parent_task_id": data.get("parent_task_id"),
        "timestamp": data.get("timestamp"),
        "sequence": sequence,
        "payload": payload,
    }
    return out
