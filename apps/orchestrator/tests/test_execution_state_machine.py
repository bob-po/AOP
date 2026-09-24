"""Phase 3 — execution state machine unit tests."""

from __future__ import annotations

import pytest

from execution.state_machine import (
    AgentLifecycleState,
    AgentLifecycleStateMachine,
    ExecutionState,
    ExecutionStateMachine,
    IllegalTransition,
    RecoveryClass,
)


def test_valid_happy_path():
    cur = ExecutionState.PENDING
    for nxt in (ExecutionState.RUNNING, ExecutionState.SUCCEEDED):
        r = ExecutionStateMachine.transition(cur, nxt)
        assert r.changed
        cur = r.state  # type: ignore[assignment]
    assert cur == ExecutionState.SUCCEEDED


def test_idempotent_same_state():
    r = ExecutionStateMachine.transition(ExecutionState.RUNNING, ExecutionState.RUNNING)
    assert r.changed is False


def test_illegal_transition_rejected():
    with pytest.raises(IllegalTransition):
        ExecutionStateMachine.transition(ExecutionState.PENDING, ExecutionState.SUCCEEDED)


def test_terminal_protection_blocks_late_success():
    with pytest.raises(IllegalTransition):
        ExecutionStateMachine.transition(ExecutionState.TIMEOUT, ExecutionState.SUCCEEDED)
    with pytest.raises(IllegalTransition):
        ExecutionStateMachine.transition(ExecutionState.CANCELLED, ExecutionState.RUNNING)
    with pytest.raises(IllegalTransition):
        ExecutionStateMachine.transition(ExecutionState.SUCCEEDED, ExecutionState.FAILED)


def test_timeout_can_retry_when_allowed():
    r = ExecutionStateMachine.transition(
        ExecutionState.TIMEOUT, ExecutionState.RETRYING, allow_recover_retry=True
    )
    assert r.state == ExecutionState.RETRYING


def test_recovery_class():
    assert (
        ExecutionStateMachine.recovery_class(ExecutionState.SUCCEEDED)
        == RecoveryClass.TERMINAL
    )
    assert (
        ExecutionStateMachine.recovery_class(ExecutionState.RUNNING, stale=False)
        == RecoveryClass.RUNNING
    )
    assert (
        ExecutionStateMachine.recovery_class(ExecutionState.RUNNING, stale=True)
        == RecoveryClass.RECOVERABLE
    )
    assert (
        ExecutionStateMachine.recovery_class(ExecutionState.TIMEOUT)
        == RecoveryClass.RECOVERABLE
    )


def test_agent_lifecycle_drain_path():
    r = AgentLifecycleStateMachine.transition(
        AgentLifecycleState.READY, AgentLifecycleState.DRAINING
    )
    assert r.event_type == "agent.draining"
    r2 = AgentLifecycleStateMachine.transition(
        AgentLifecycleState.DRAINING, AgentLifecycleState.OFFLINE
    )
    assert r2.state == AgentLifecycleState.OFFLINE


def test_agent_accepts_work():
    assert AgentLifecycleStateMachine.accepts_work(AgentLifecycleState.READY)
    assert AgentLifecycleStateMachine.accepts_work(AgentLifecycleState.BUSY)
    assert not AgentLifecycleStateMachine.accepts_work(AgentLifecycleState.DRAINING)
    assert not AgentLifecycleStateMachine.accepts_work(AgentLifecycleState.OFFLINE)
