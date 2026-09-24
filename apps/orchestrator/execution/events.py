"""Phase 3 — unified execution events (propagation layer)."""

from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionEvent:
    event_type: str
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: str = field(default_factory=_utc_now)
    root_task_id: Optional[str] = None
    correlation_id: Optional[str] = None
    task_id: Optional[str] = None
    agent_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ExecutionEventBus:
    """In-memory ordered event log + optional fan-out hooks.

    Phase 4: assigns per-root ``sequence`` for collaboration stream ordering.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._events: list[ExecutionEvent] = []
        self._seen_ids: set[str] = set()
        self._hooks: list = []
        self._root_seq: dict[str, int] = {}

    def on_emit(self, hook) -> None:
        self._hooks.append(hook)

    def emit(self, event: ExecutionEvent | dict[str, Any]) -> ExecutionEvent:
        if isinstance(event, dict):
            event = ExecutionEvent(**{k: v for k, v in event.items() if k in ExecutionEvent.__dataclass_fields__})
        with self._lock:
            if event.event_id in self._seen_ids:
                # Idempotent: duplicate event_id is a no-op
                for e in self._events:
                    if e.event_id == event.event_id:
                        return e
            self._seen_ids.add(event.event_id)
            root = event.root_task_id or event.task_id or "_"
            seq = self._root_seq.get(root, 0) + 1
            self._root_seq[root] = seq
            if "sequence" not in event.payload:
                event.payload = {**(event.payload or {}), "sequence": seq}
            self._events.append(event)
        for hook in list(self._hooks):
            try:
                hook(event)
            except Exception:  # noqa: BLE001 - hooks must not break emission
                pass
        return event

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._events if e.task_id == task_id]

    def list_for_root(self, root_task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._events if e.root_task_id == root_task_id]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._seen_ids.clear()


# Canonical event type constants
TASK_CREATED = "task.created"
TASK_STARTED = "task.started"
TASK_WAITING = "task.waiting"
TASK_RETRYING = "task.retrying"
TASK_COMPLETED = "task.completed"
TASK_FAILED = "task.failed"
TASK_TIMEOUT = "task.timeout"
TASK_CANCELLED = "task.cancelled"

DELEGATION_REQUESTED = "delegation.requested"
DELEGATION_ACCEPTED = "delegation.accepted"
DELEGATION_STARTED = "delegation.started"
DELEGATION_COMPLETED = "delegation.completed"
DELEGATION_FAILED = "delegation.failed"
DELEGATION_RELEASED = "delegation.released"

AGENT_REGISTERED = "agent.registered"
AGENT_READY = "agent.ready"
AGENT_BUSY = "agent.busy"
AGENT_DRAINING = "agent.draining"
AGENT_OFFLINE = "agent.offline"


__all__ = [
    "ExecutionEvent",
    "ExecutionEventBus",
    "TASK_CREATED",
    "TASK_STARTED",
    "TASK_WAITING",
    "TASK_RETRYING",
    "TASK_COMPLETED",
    "TASK_FAILED",
    "TASK_TIMEOUT",
    "TASK_CANCELLED",
    "DELEGATION_REQUESTED",
    "DELEGATION_ACCEPTED",
    "DELEGATION_STARTED",
    "DELEGATION_COMPLETED",
    "DELEGATION_FAILED",
    "DELEGATION_RELEASED",
    "AGENT_REGISTERED",
    "AGENT_READY",
    "AGENT_BUSY",
    "AGENT_DRAINING",
    "AGENT_OFFLINE",
]
