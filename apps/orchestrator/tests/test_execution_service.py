"""Phase 3 — execution record, retry, recover, cancel, late callback."""

from __future__ import annotations

import pytest

from execution import ExecutionService, IllegalTransition, RetryPolicy
from execution.state_machine import ExecutionState, RecoveryClass


@pytest.fixture
def svc():
    return ExecutionService(retry_policy=RetryPolicy(max_retries=3, base_delay_s=0.5))


def test_create_and_succeed(svc: ExecutionService):
    rec = svc.create(task_id="t1", root_task_id="t1", correlation_id="c1", agent_id="A")
    assert rec.state == "PENDING"
    svc.start("t1")
    done = svc.succeed("t1")
    assert done.state == "SUCCEEDED"
    assert done.finished_at
    events = svc.events.list_for_task("t1")
    types = [e["event_type"] for e in events]
    assert "task.created" in types
    assert "task.started" in types
    assert "task.completed" in types


def test_idempotent_create_by_idempotency_key(svc: ExecutionService):
    a = svc.create(task_id="t-a", idempotency_key="a2a-del-same", root_task_id="r")
    b = svc.create(task_id="t-b", idempotency_key="a2a-del-same", root_task_id="r")
    assert a.task_id == b.task_id == "t-a"


def test_duplicate_callback_no_regression(svc: ExecutionService):
    svc.create(task_id="t2", root_task_id="t2")
    svc.start("t2")
    svc.succeed("t2")
    again = svc.apply_callback("t2", success=False, error="late")
    assert again.state == "SUCCEEDED"


def test_timeout_then_late_success_ignored(svc: ExecutionService):
    svc.create(task_id="t3", root_task_id="t3")
    svc.start("t3")
    svc.timeout("t3")
    late = svc.apply_callback("t3", success=True)
    assert late.state == "TIMEOUT"


def test_retry_backoff_and_exhaustion(svc: ExecutionService):
    svc.create(task_id="t4", root_task_id="t4", max_retries=2)
    svc.start("t4")
    svc.timeout("t4")
    r1 = svc.mark_retry("t4", error_code="TIMEOUT")
    assert r1.state == "RETRYING"
    assert r1.attempt == 1
    assert r1.metadata["next_delay_s"] == 0.5  # base * 2^0
    svc.start("t4")
    svc.timeout("t4")
    r2 = svc.mark_retry("t4", error_code="TIMEOUT")
    assert r2.attempt == 2
    svc.start("t4")
    svc.timeout("t4")
    r3 = svc.mark_retry("t4", error_code="TIMEOUT")
    assert r3.state == "FAILED"
    assert "exhausted" in (r3.error or "")


def test_retry_preserves_lineage_identity(svc: ExecutionService):
    svc.create(
        task_id="t5",
        root_task_id="root-x",
        correlation_id="corr-x",
        idempotency_key="a2a-del-t5",
        branch_lineage=["A", "B"],
    )
    svc.start("t5")
    svc.timeout("t5")
    r = svc.mark_retry("t5", error_code="TIMEOUT")
    assert r.root_task_id == "root-x"
    assert r.correlation_id == "corr-x"
    assert r.task_id == "t5"
    assert r.idempotency_key == "a2a-del-t5"
    assert r.branch_lineage == ["A", "B"]


def test_recover_stale_running(svc: ExecutionService):
    svc.create(task_id="t6", root_task_id="t6")
    svc.start("t6")
    # Force stale classification via recover(stale_after_s=0)
    classification = svc.store.classify("t6", stale_after_s=0)
    assert classification["class"] == RecoveryClass.RECOVERABLE.value
    out = svc.recover("t6", stale_after_s=0)
    assert out["action"] == "retry"
    assert out["ownership_token"]
    # Concurrent recover loses ownership
    out2 = svc.recover("t6", stale_after_s=0)
    assert out2["action"] == "contention"


def test_recover_completed_is_noop(svc: ExecutionService):
    svc.create(task_id="t7", root_task_id="t7")
    svc.start("t7")
    svc.succeed("t7")
    out = svc.recover("t7")
    assert out["action"] == "none"
    assert out["class"] == RecoveryClass.TERMINAL.value


def test_cancel_tree_skips_terminal(svc: ExecutionService):
    svc.create(task_id="root", root_task_id="root")
    svc.start("root")
    svc.create(task_id="child", root_task_id="root", parent_task_id="root")
    svc.start("child")
    svc.succeed("child")
    out = svc.cancel_tree("root")
    assert any(c["task_id"] == "root" for c in out["cancelled"])
    assert any(s["task_id"] == "child" for s in out["skipped"])


def test_event_idempotent_by_event_id(svc: ExecutionService):
    from execution.events import ExecutionEvent

    e = ExecutionEvent(event_type="task.started", event_id="fixed-id", task_id="x")
    svc.events.emit(e)
    svc.events.emit(e)
    assert len([x for x in svc.events.list_for_task("x") if x["event_id"] == "fixed-id"]) == 1
