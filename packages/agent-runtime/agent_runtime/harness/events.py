"""Bridge harness stream events ↔ A2A task store / ExecutionEvent-shaped dicts."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .protocol import HarnessEvent, HarnessEventType, HarnessResult, HarnessStatus, SCHEMA_VERSION


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def data_part(data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "data", "data": data}


def new_working_task(
    task_id: str,
    *,
    skill_id: str,
    correlation_id: Optional[str] = None,
    root_task_id: Optional[str] = None,
    parent_task_id: Optional[str] = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {"skillId": skill_id, "harness": True, "schemaVersion": SCHEMA_VERSION}
    if correlation_id:
        meta["correlationId"] = correlation_id
    if root_task_id:
        meta["rootTaskId"] = root_task_id
    if parent_task_id:
        meta["parentTaskId"] = parent_task_id
    return {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "working", "timestamp": utc_now()},
        "artifacts": [],
        "metadata": meta,
        "correlationId": correlation_id,
        "rootTaskId": root_task_id or task_id,
    }


def apply_event(task: dict[str, Any], event: HarnessEvent) -> dict[str, Any]:
    """Mutate task in place from a harness stream event. Returns the task."""
    status = task.setdefault("status", {})
    if not isinstance(status, dict):
        status = {"state": str(status)}
        task["status"] = status

    et = event.type if isinstance(event.type, HarnessEventType) else HarnessEventType(str(event.type))
    payload = event.payload or {}
    status["timestamp"] = event.timestamp or utc_now()

    if et == HarnessEventType.STATUS:
        state = str(payload.get("state") or "working")
        status["state"] = state
        msg = payload.get("message")
        if msg:
            status["message"] = {"role": "agent", "parts": [text_part(str(msg)[:2000])]}
    elif et == HarnessEventType.DELTA:
        delta = str(payload.get("text") or "")
        if delta:
            # Keep a single growing working message for subscribe clients.
            prev = ""
            existing = status.get("message") or {}
            parts = existing.get("parts") if isinstance(existing, dict) else None
            if parts and parts[0].get("type") == "text":
                prev = str(parts[0].get("text") or "")
            status["message"] = {"role": "agent", "parts": [text_part((prev + delta)[:8000])]}
            status["state"] = "working"
    elif et == HarnessEventType.ERROR:
        status["state"] = "failed"
        err = str(payload.get("error") or payload.get("message") or "harness error")
        status["message"] = {"role": "agent", "parts": [text_part(err[:2000])]}
    elif et == HarnessEventType.USAGE:
        meta = task.setdefault("metadata", {})
        usage = dict(meta.get("usage") or {})
        usage.update({k: v for k, v in payload.items() if v is not None})
        meta["usage"] = usage
    elif et == HarnessEventType.FINAL:
        state = str(payload.get("state") or "completed")
        status["state"] = state

    # Local sequence for subscribe ordering (mirrors ExecutionEvent.payload.sequence).
    meta = task.setdefault("metadata", {})
    seq = int(meta.get("_event_seq") or 0) + 1
    meta["_event_seq"] = seq
    events = task.setdefault("_events", [])
    events.append(
        {
            "event_type": f"harness.{et.value}",
            "event_id": uuid.uuid4().hex,
            "timestamp": event.timestamp or utc_now(),
            "task_id": task.get("id"),
            "root_task_id": task.get("rootTaskId") or meta.get("rootTaskId"),
            "correlation_id": task.get("correlationId") or meta.get("correlationId"),
            "agent_id": meta.get("agentId"),
            "payload": {**(payload or {}), "sequence": seq},
        }
    )
    return task


def finalize_task(task: dict[str, Any], result: HarnessResult) -> dict[str, Any]:
    """Attach summary + result artifacts and set terminal status."""
    status_map = {
        HarnessStatus.OK: "completed",
        HarnessStatus.FAILED: "failed",
        HarnessStatus.CANCELED: "canceled",
        HarnessStatus.TIMEOUT: "failed",
    }
    state = status_map.get(result.status, "failed")
    task["status"] = {
        "state": state,
        "timestamp": utc_now(),
    }
    if result.error or state != "completed":
        msg = result.error or result.text or state
        task["status"]["message"] = {"role": "agent", "parts": [text_part(str(msg)[:2000])]}

    data = result.to_data_part()
    task["artifacts"] = [
        {
            "artifactId": str(uuid.uuid4()),
            "name": "summary",
            "description": "Human-readable harness summary",
            "parts": [text_part(result.text or "")],
        },
        {
            "artifactId": str(uuid.uuid4()),
            "name": "result",
            "description": "Schema-normalized harness result",
            "parts": [data_part(data)],
        },
    ]
    meta = task.setdefault("metadata", {})
    meta["skillId"] = result.skill_id or meta.get("skillId")
    meta["schemaVersion"] = SCHEMA_VERSION
    meta["usage"] = result.usage.to_dict()
    meta["harnessStatus"] = (
        result.status.value if isinstance(result.status, HarnessStatus) else str(result.status)
    )
    return task


def to_execution_event_dict(raw: dict[str, Any], *, agent_id: Optional[str] = None) -> dict[str, Any]:
    """Normalize a stored harness event into ExecutionEvent field names."""
    return {
        "event_type": raw.get("event_type") or "harness.event",
        "event_id": raw.get("event_id") or uuid.uuid4().hex,
        "timestamp": raw.get("timestamp") or utc_now(),
        "root_task_id": raw.get("root_task_id"),
        "correlation_id": raw.get("correlation_id"),
        "task_id": raw.get("task_id"),
        "agent_id": agent_id or raw.get("agent_id"),
        "parent_task_id": raw.get("parent_task_id"),
        "payload": dict(raw.get("payload") or {}),
    }


__all__ = [
    "utc_now",
    "text_part",
    "data_part",
    "new_working_task",
    "apply_event",
    "finalize_task",
    "to_execution_event_dict",
]
