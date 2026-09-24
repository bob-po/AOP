"""Phase 4 — capacity WAIT queue (FIFO + priority)."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class QueueEntry:
    task_id: str
    agent_id: str
    root_task_id: Optional[str] = None
    correlation_id: Optional[str] = None
    priority: int = 100
    state: str = "WAITING"
    queued_at: str = field(default_factory=lambda: _utc_now().isoformat())
    timeout_at: Optional[str] = None
    position: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CapacityQueue:
    """In-memory capacity queue for hermetic tests; Postgres optional later."""

    def __init__(self, *, max_depth: int = 100):
        self.max_depth = max_depth
        self._lock = threading.RLock()
        self._by_agent: dict[str, list[QueueEntry]] = {}
        self._by_task: dict[str, QueueEntry] = {}

    def enqueue(
        self,
        *,
        task_id: str,
        agent_id: str,
        root_task_id: str | None = None,
        correlation_id: str | None = None,
        priority: int = 100,
        timeout_s: float = 300.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if task_id in self._by_task and self._by_task[task_id].state == "WAITING":
                return {"queued": True, "duplicate": True, **self._by_task[task_id].to_dict()}
            q = self._by_agent.setdefault(agent_id, [])
            waiting = [e for e in q if e.state == "WAITING"]
            if len(waiting) >= self.max_depth:
                return {
                    "queued": False,
                    "rejected": True,
                    "reason": "max_queue_depth",
                    "depth": len(waiting),
                    "max_depth": self.max_depth,
                }
            entry = QueueEntry(
                task_id=task_id,
                agent_id=agent_id,
                root_task_id=root_task_id,
                correlation_id=correlation_id,
                priority=priority,
                timeout_at=(_utc_now() + timedelta(seconds=timeout_s)).isoformat(),
                metadata=dict(metadata or {}),
            )
            q.append(entry)
            q.sort(key=lambda e: (e.priority, e.queued_at))
            self._reindex(agent_id)
            self._by_task[task_id] = entry
            return {"queued": True, "rejected": False, **entry.to_dict()}

    def dequeue(self, agent_id: str) -> Optional[QueueEntry]:
        with self._lock:
            q = self._by_agent.get(agent_id) or []
            for entry in q:
                if entry.state != "WAITING":
                    continue
                if entry.timeout_at:
                    try:
                        if _utc_now() > datetime.fromisoformat(entry.timeout_at):
                            entry.state = "EXPIRED"
                            continue
                    except ValueError:
                        pass
                entry.state = "CLAIMED"
                self._reindex(agent_id)
                return QueueEntry(**entry.to_dict())
            return None

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            entry = self._by_task.get(task_id)
            if not entry or entry.state != "WAITING":
                return False
            entry.state = "CANCELLED"
            return True

    def depth(self, agent_id: str) -> int:
        with self._lock:
            return sum(
                1 for e in (self._by_agent.get(agent_id) or []) if e.state == "WAITING"
            )

    def _reindex(self, agent_id: str) -> None:
        pos = 0
        for e in self._by_agent.get(agent_id) or []:
            if e.state == "WAITING":
                pos += 1
                e.position = pos


__all__ = ["CapacityQueue", "QueueEntry"]
