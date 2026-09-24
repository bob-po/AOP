"""Phase 3 — Agent lifecycle (REGISTERED→READY→BUSY→DRAINING→OFFLINE)."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from execution.state_machine import (
    AgentLifecycleState,
    AgentLifecycleStateMachine,
    IllegalTransition,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentLifecycleRecord:
    agent_id: str
    state: str = AgentLifecycleState.REGISTERED.value
    last_seen: Optional[str] = None
    active_tasks: int = 0
    max_concurrency: int = 8
    load: float = 0.0
    version: Optional[str] = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    drain_started_at: Optional[str] = None
    updated_at: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentLifecycleService:
    """In-memory lifecycle authority (DB wiring optional later)."""

    def __init__(self, event_bus=None):
        self._lock = threading.RLock()
        self._agents: dict[str, AgentLifecycleRecord] = {}
        self._events = event_bus

    def register(
        self,
        agent_id: str,
        *,
        version: str | None = None,
        capabilities: dict[str, Any] | None = None,
        max_concurrency: int = 8,
    ) -> AgentLifecycleRecord:
        with self._lock:
            existing = self._agents.get(agent_id)
            if existing:
                existing.last_seen = _utc_now()
                existing.updated_at = existing.last_seen
                if version:
                    existing.version = version
                if capabilities:
                    existing.capabilities.update(capabilities)
                return AgentLifecycleRecord(**existing.to_dict())
            rec = AgentLifecycleRecord(
                agent_id=agent_id,
                state=AgentLifecycleState.REGISTERED.value,
                last_seen=_utc_now(),
                updated_at=_utc_now(),
                version=version,
                capabilities=dict(capabilities or {}),
                max_concurrency=max_concurrency,
            )
            self._agents[agent_id] = rec
            self._emit(AgentLifecycleStateMachine.event_for(AgentLifecycleState.REGISTERED), rec)
            return AgentLifecycleRecord(**rec.to_dict())

    def transition(self, agent_id: str, target: AgentLifecycleState | str) -> AgentLifecycleRecord:
        with self._lock:
            rec = self._require(agent_id)
            result = AgentLifecycleStateMachine.transition(rec.state, target)
            if result.changed:
                rec.state = result.state.value  # type: ignore[union-attr]
                rec.updated_at = _utc_now()
                if result.state == AgentLifecycleState.DRAINING:
                    rec.drain_started_at = rec.updated_at
                self._emit(result.event_type, rec)
            return AgentLifecycleRecord(**rec.to_dict())

    def mark_ready(self, agent_id: str) -> AgentLifecycleRecord:
        return self.transition(agent_id, AgentLifecycleState.READY)

    def heartbeat(
        self,
        agent_id: str,
        *,
        active_tasks: int | None = None,
        load: float | None = None,
        version: str | None = None,
        capabilities: dict[str, Any] | None = None,
    ) -> AgentLifecycleRecord:
        with self._lock:
            if agent_id not in self._agents:
                self.register(agent_id, version=version, capabilities=capabilities)
            rec = self._agents[agent_id]
            rec.last_seen = _utc_now()
            rec.updated_at = rec.last_seen
            if active_tasks is not None:
                rec.active_tasks = max(0, int(active_tasks))
            if load is not None:
                rec.load = float(load)
            if version:
                rec.version = version
            if capabilities:
                rec.capabilities.update(capabilities)
            # Auto READY/BUSY from heartbeat when not draining
            if rec.state == AgentLifecycleState.OFFLINE.value:
                # P4.18: OFFLINE → REGISTERED → READY (never OFFLINE → BUSY)
                try:
                    r1 = AgentLifecycleStateMachine.transition(
                        rec.state, AgentLifecycleState.REGISTERED
                    )
                    if r1.changed:
                        rec.state = r1.state.value  # type: ignore[union-attr]
                        self._emit(r1.event_type, rec)
                    r2 = AgentLifecycleStateMachine.transition(
                        rec.state, AgentLifecycleState.READY
                    )
                    if r2.changed:
                        rec.state = r2.state.value  # type: ignore[union-attr]
                        self._emit(r2.event_type, rec)
                except IllegalTransition:
                    pass
            elif rec.state not in {
                AgentLifecycleState.DRAINING.value,
            }:
                desired = (
                    AgentLifecycleState.BUSY
                    if rec.active_tasks > 0
                    else AgentLifecycleState.READY
                )
                if rec.state == AgentLifecycleState.REGISTERED.value:
                    desired = AgentLifecycleState.READY
                try:
                    result = AgentLifecycleStateMachine.transition(rec.state, desired)
                    if result.changed:
                        rec.state = result.state.value  # type: ignore[union-attr]
                        self._emit(result.event_type, rec)
                except IllegalTransition:
                    pass
            return AgentLifecycleRecord(**rec.to_dict())

    def drain(self, agent_id: str) -> AgentLifecycleRecord:
        rec = self.transition(agent_id, AgentLifecycleState.DRAINING)
        # If no active work, move to OFFLINE immediately
        with self._lock:
            live = self._agents[agent_id]
            if live.active_tasks <= 0 and live.state == AgentLifecycleState.DRAINING.value:
                return self.transition(agent_id, AgentLifecycleState.OFFLINE)
        return rec

    def on_task_started(self, agent_id: str) -> AgentLifecycleRecord:
        with self._lock:
            if agent_id not in self._agents:
                self.register(agent_id)
            rec = self._agents[agent_id]
            if not AgentLifecycleStateMachine.accepts_work(rec.state):
                raise IllegalTransition(
                    AgentLifecycleState(rec.state),
                    AgentLifecycleState.BUSY,
                    kind="agent_lifecycle",
                )
            rec.active_tasks += 1
            return self.transition(agent_id, AgentLifecycleState.BUSY)

    def on_task_finished(self, agent_id: str) -> AgentLifecycleRecord:
        with self._lock:
            rec = self._require(agent_id)
            rec.active_tasks = max(0, rec.active_tasks - 1)
            rec.updated_at = _utc_now()
            if rec.state == AgentLifecycleState.DRAINING.value and rec.active_tasks == 0:
                return self.transition(agent_id, AgentLifecycleState.OFFLINE)
            if rec.active_tasks == 0 and rec.state == AgentLifecycleState.BUSY.value:
                return self.transition(agent_id, AgentLifecycleState.READY)
            return AgentLifecycleRecord(**rec.to_dict())

    def health(self, agent_id: str, *, stale_after_s: float = 60.0) -> dict[str, Any]:
        with self._lock:
            rec = self._agents.get(agent_id)
            if not rec:
                return {
                    "agent_id": agent_id,
                    "healthy": False,
                    "state": None,
                    "reason": "not_registered",
                }
            stale = False
            if rec.last_seen:
                try:
                    age = (
                        datetime.now(timezone.utc) - datetime.fromisoformat(rec.last_seen)
                    ).total_seconds()
                    stale = age > stale_after_s
                except ValueError:
                    stale = True
            accepts = AgentLifecycleStateMachine.accepts_work(rec.state) and not stale
            at_capacity = rec.active_tasks >= rec.max_concurrency
            return {
                "agent_id": agent_id,
                "healthy": accepts and not at_capacity,
                "state": rec.state,
                "last_seen": rec.last_seen,
                "active_tasks": rec.active_tasks,
                "max_concurrency": rec.max_concurrency,
                "load": rec.load,
                "version": rec.version,
                "capabilities": rec.capabilities,
                "stale": stale,
                "at_capacity": at_capacity,
                "accepts_work": accepts,
            }

    def accepts_delegation(self, agent_id: str) -> tuple[bool, str]:
        h = self.health(agent_id)
        if not h.get("state"):
            # Legacy agents without lifecycle still allowed (capability detection)
            return True, "legacy_untracked"
        if h["state"] == AgentLifecycleState.DRAINING.value:
            return False, "draining"
        if h["state"] == AgentLifecycleState.OFFLINE.value:
            return False, "offline"
        if h.get("stale"):
            return False, "heartbeat_stale"
        if h.get("at_capacity"):
            return False, "at_capacity"
        if not h.get("accepts_work"):
            return False, f"state:{h['state']}"
        return True, "ok"

    def mark_stale_offline(self, *, stale_after_s: float = 60.0) -> list[str]:
        """P4.8/P4.18: heartbeat timeout → OFFLINE for all stale agents."""
        offline: list[str] = []
        with self._lock:
            ids = list(self._agents.keys())
        for agent_id in ids:
            h = self.health(agent_id, stale_after_s=stale_after_s)
            if not h.get("stale"):
                continue
            if h.get("state") in {
                AgentLifecycleState.OFFLINE.value,
                None,
            }:
                continue
            try:
                with self._lock:
                    rec = self._agents.get(agent_id)
                    if not rec:
                        continue
                    if rec.state == AgentLifecycleState.OFFLINE.value:
                        continue
                    # Force OFFLINE via allowed path: DRAINING→OFFLINE or direct
                    if rec.state != AgentLifecycleState.DRAINING.value:
                        try:
                            AgentLifecycleStateMachine.transition(
                                rec.state, AgentLifecycleState.DRAINING
                            )
                            rec.state = AgentLifecycleState.DRAINING.value
                            self._emit("agent.draining", rec)
                        except IllegalTransition:
                            # REGISTERED can go OFFLINE? check machine — use DRAINING first
                            pass
                    try:
                        result = AgentLifecycleStateMachine.transition(
                            rec.state, AgentLifecycleState.OFFLINE
                        )
                        if result.changed:
                            rec.state = result.state.value  # type: ignore[union-attr]
                            rec.updated_at = _utc_now()
                            self._emit(result.event_type, rec)
                            offline.append(agent_id)
                    except IllegalTransition:
                        # Last resort: set OFFLINE for recovery scanning
                        rec.state = AgentLifecycleState.OFFLINE.value
                        rec.updated_at = _utc_now()
                        self._emit("agent.offline", rec)
                        offline.append(agent_id)
            except Exception:  # noqa: BLE001
                continue
        return offline

    def get(self, agent_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            rec = self._agents.get(agent_id)
            return rec.to_dict() if rec else None

    def list_agent_ids(self) -> list[str]:
        with self._lock:
            return list(self._agents.keys())

    def router_accepts(self, agent_id: str) -> tuple[bool, str]:
        """P4.15: READY/BUSY + healthy + capacity available."""
        h = self.health(agent_id)
        if not h.get("state"):
            return True, "legacy_untracked"
        state = h["state"]
        if state in {
            AgentLifecycleState.DRAINING.value,
            AgentLifecycleState.OFFLINE.value,
        }:
            return False, f"lifecycle:{state}"
        if h.get("stale"):
            return False, "heartbeat_stale"
        if state not in {
            AgentLifecycleState.READY.value,
            AgentLifecycleState.BUSY.value,
            AgentLifecycleState.REGISTERED.value,
        }:
            return False, f"lifecycle:{state}"
        if h.get("at_capacity"):
            return False, "at_capacity"
        return True, "ok"

    def _require(self, agent_id: str) -> AgentLifecycleRecord:
        rec = self._agents.get(agent_id)
        if not rec:
            raise KeyError(f"agent not registered: {agent_id}")
        return rec

    def _emit(self, event_type: str, rec: AgentLifecycleRecord) -> None:
        if not self._events:
            return
        from execution.events import ExecutionEvent

        self._events.emit(
            ExecutionEvent(
                event_type=event_type,
                agent_id=rec.agent_id,
                payload={
                    "state": rec.state,
                    "active_tasks": rec.active_tasks,
                    "max_concurrency": rec.max_concurrency,
                },
            )
        )


__all__ = ["AgentLifecycleService", "AgentLifecycleRecord", "IllegalTransition"]
