"""Phase 3 — execution & agent lifecycle state machines.

Illegal transitions are rejected. Terminal states are irreversible
(late callbacks / duplicate events cannot roll state backwards).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable


class ExecutionState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class AgentLifecycleState(str, Enum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    BUSY = "BUSY"
    DRAINING = "DRAINING"
    OFFLINE = "OFFLINE"


class RecoveryClass(str, Enum):
    UNKNOWN = "UNKNOWN"
    RUNNING = "RUNNING"
    RECOVERABLE = "RECOVERABLE"
    TERMINAL = "TERMINAL"


TERMINAL_EXECUTION = frozenset({
    ExecutionState.SUCCEEDED,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
    ExecutionState.TIMEOUT,
})

# Legal directed edges. Self-transitions (same→same) are treated as idempotent no-ops.
_EXEC_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.PENDING: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.WAITING,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
    }),
    ExecutionState.RUNNING: frozenset({
        ExecutionState.WAITING,
        ExecutionState.RETRYING,
        ExecutionState.SUCCEEDED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMEOUT,
    }),
    ExecutionState.WAITING: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.RETRYING,
        ExecutionState.CANCELLED,
        ExecutionState.TIMEOUT,
        ExecutionState.FAILED,
    }),
    ExecutionState.RETRYING: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
        ExecutionState.TIMEOUT,
    }),
    ExecutionState.SUCCEEDED: frozenset(),
    ExecutionState.FAILED: frozenset({ExecutionState.RETRYING}),  # recover→retry only via recover()
    ExecutionState.CANCELLED: frozenset(),
    ExecutionState.TIMEOUT: frozenset({ExecutionState.RETRYING, ExecutionState.FAILED}),
}

_AGENT_TRANSITIONS: dict[AgentLifecycleState, frozenset[AgentLifecycleState]] = {
    AgentLifecycleState.REGISTERED: frozenset({
        AgentLifecycleState.READY,
        AgentLifecycleState.OFFLINE,
    }),
    AgentLifecycleState.READY: frozenset({
        AgentLifecycleState.BUSY,
        AgentLifecycleState.DRAINING,
        AgentLifecycleState.OFFLINE,
    }),
    AgentLifecycleState.BUSY: frozenset({
        AgentLifecycleState.READY,
        AgentLifecycleState.BUSY,
        AgentLifecycleState.DRAINING,
        AgentLifecycleState.OFFLINE,
    }),
    AgentLifecycleState.DRAINING: frozenset({
        AgentLifecycleState.OFFLINE,
        AgentLifecycleState.READY,
        AgentLifecycleState.BUSY,  # still finishing work
    }),
    AgentLifecycleState.OFFLINE: frozenset({
        AgentLifecycleState.REGISTERED,
        AgentLifecycleState.READY,
    }),
}


class IllegalTransition(ValueError):
    def __init__(self, current: Enum, target: Enum, *, kind: str = "execution"):
        self.current = current
        self.target = target
        self.kind = kind
        super().__init__(f"illegal {kind} transition {current.value} → {target.value}")


def _coerce_exec(state: ExecutionState | str) -> ExecutionState:
    if isinstance(state, ExecutionState):
        return state
    return ExecutionState(str(state).upper())


def _coerce_agent(state: AgentLifecycleState | str) -> AgentLifecycleState:
    if isinstance(state, AgentLifecycleState):
        return state
    return AgentLifecycleState(str(state).upper())


@dataclass(frozen=True)
class TransitionResult:
    state: Enum
    changed: bool
    event_type: str


class ExecutionStateMachine:
    """Authoritative execution-state transitions with terminal protection."""

    TERMINAL = TERMINAL_EXECUTION

    @classmethod
    def can_transition(cls, current: ExecutionState | str, target: ExecutionState | str) -> bool:
        cur, tgt = _coerce_exec(current), _coerce_exec(target)
        if cur == tgt:
            return True
        return tgt in _EXEC_TRANSITIONS.get(cur, frozenset())

    @classmethod
    def transition(
        cls,
        current: ExecutionState | str,
        target: ExecutionState | str,
        *,
        allow_recover_retry: bool = False,
    ) -> TransitionResult:
        cur, tgt = _coerce_exec(current), _coerce_exec(target)
        if cur == tgt:
            return TransitionResult(state=cur, changed=False, event_type="task.noop")
        # Terminal protection: never overwrite SUCCEEDED/CANCELLED; FAILED/TIMEOUT
        # may move to RETRYING only when recover explicitly allows it.
        if cur in TERMINAL_EXECUTION:
            if cur in {ExecutionState.SUCCEEDED, ExecutionState.CANCELLED}:
                raise IllegalTransition(cur, tgt)
            if cur == ExecutionState.FAILED and tgt == ExecutionState.RETRYING and allow_recover_retry:
                return TransitionResult(state=tgt, changed=True, event_type="task.retrying")
            if cur == ExecutionState.TIMEOUT and tgt in {
                ExecutionState.RETRYING,
                ExecutionState.FAILED,
            }:
                if tgt == ExecutionState.RETRYING and not allow_recover_retry:
                    raise IllegalTransition(cur, tgt)
                return TransitionResult(
                    state=tgt,
                    changed=True,
                    event_type="task.retrying" if tgt == ExecutionState.RETRYING else "task.failed",
                )
            raise IllegalTransition(cur, tgt)
        if tgt not in _EXEC_TRANSITIONS.get(cur, frozenset()):
            raise IllegalTransition(cur, tgt)
        return TransitionResult(state=tgt, changed=True, event_type=cls.event_for(tgt))

    @staticmethod
    def event_for(state: ExecutionState | str) -> str:
        s = _coerce_exec(state)
        return {
            ExecutionState.PENDING: "task.created",
            ExecutionState.RUNNING: "task.started",
            ExecutionState.WAITING: "task.waiting",
            ExecutionState.RETRYING: "task.retrying",
            ExecutionState.SUCCEEDED: "task.completed",
            ExecutionState.FAILED: "task.failed",
            ExecutionState.CANCELLED: "task.cancelled",
            ExecutionState.TIMEOUT: "task.timeout",
        }[s]

    @classmethod
    def is_terminal(cls, state: ExecutionState | str) -> bool:
        return _coerce_exec(state) in TERMINAL_EXECUTION

    @classmethod
    def recovery_class(
        cls,
        state: ExecutionState | str,
        *,
        stale: bool = False,
        attempts_remaining: bool = True,
    ) -> RecoveryClass:
        s = _coerce_exec(state)
        if s in {ExecutionState.SUCCEEDED, ExecutionState.CANCELLED}:
            return RecoveryClass.TERMINAL
        if s == ExecutionState.FAILED and not attempts_remaining:
            return RecoveryClass.TERMINAL
        if s == ExecutionState.RUNNING and not stale:
            return RecoveryClass.RUNNING
        if s in {
            ExecutionState.PENDING,
            ExecutionState.WAITING,
            ExecutionState.RETRYING,
            ExecutionState.TIMEOUT,
            ExecutionState.FAILED,
        } or (s == ExecutionState.RUNNING and stale):
            return RecoveryClass.RECOVERABLE
        return RecoveryClass.UNKNOWN


class AgentLifecycleStateMachine:
    """OS-side agent lifecycle transitions."""

    @classmethod
    def can_transition(
        cls, current: AgentLifecycleState | str, target: AgentLifecycleState | str
    ) -> bool:
        cur, tgt = _coerce_agent(current), _coerce_agent(target)
        if cur == tgt:
            return True
        return tgt in _AGENT_TRANSITIONS.get(cur, frozenset())

    @classmethod
    def transition(
        cls, current: AgentLifecycleState | str, target: AgentLifecycleState | str
    ) -> TransitionResult:
        cur, tgt = _coerce_agent(current), _coerce_agent(target)
        if cur == tgt:
            return TransitionResult(state=cur, changed=False, event_type="agent.noop")
        if tgt not in _AGENT_TRANSITIONS.get(cur, frozenset()):
            raise IllegalTransition(cur, tgt, kind="agent_lifecycle")
        return TransitionResult(state=tgt, changed=True, event_type=cls.event_for(tgt))

    @staticmethod
    def event_for(state: AgentLifecycleState | str) -> str:
        s = _coerce_agent(state)
        return {
            AgentLifecycleState.REGISTERED: "agent.registered",
            AgentLifecycleState.READY: "agent.ready",
            AgentLifecycleState.BUSY: "agent.busy",
            AgentLifecycleState.DRAINING: "agent.draining",
            AgentLifecycleState.OFFLINE: "agent.offline",
        }[s]

    @classmethod
    def accepts_work(cls, state: AgentLifecycleState | str) -> bool:
        s = _coerce_agent(state)
        return s in {AgentLifecycleState.READY, AgentLifecycleState.BUSY}

    @classmethod
    def allowed_targets(cls, current: AgentLifecycleState | str) -> Iterable[AgentLifecycleState]:
        cur = _coerce_agent(current)
        return sorted(_AGENT_TRANSITIONS.get(cur, frozenset()), key=lambda x: x.value)


__all__ = [
    "ExecutionState",
    "AgentLifecycleState",
    "RecoveryClass",
    "IllegalTransition",
    "TransitionResult",
    "ExecutionStateMachine",
    "AgentLifecycleStateMachine",
    "TERMINAL_EXECUTION",
]
