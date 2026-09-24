"""Phase 3 — reliability scenarios (crash, duplicate, concurrent ownership)."""

from __future__ import annotations

from execution import ExecutionService, RetryPolicy
from execution.state_machine import RecoveryClass


def test_agent_crash_leaves_recoverable_not_permanent_running():
    svc = ExecutionService(retry_policy=RetryPolicy(max_retries=3))
    svc.create(
        task_id="b-task",
        root_task_id="root",
        correlation_id="corr",
        parent_task_id="a-task",
        agent_id="B",
        idempotency_key="a2a-del-ab",
        branch_lineage=["A", "B"],
    )
    svc.start("b-task")
    # Crash: no completion. Classify with stale window 0 → RECOVERABLE.
    klass = svc.store.classify("b-task", stale_after_s=0)["class"]
    assert klass == RecoveryClass.RECOVERABLE.value
    out = svc.recover("b-task", stale_after_s=0)
    assert out["action"] == "retry"
    assert out["record"]["root_task_id"] == "root"
    assert out["record"]["correlation_id"] == "corr"
    assert out["record"]["idempotency_key"] == "a2a-del-ab"


def test_network_timeout_with_late_completion_uses_terminal_protection():
    svc = ExecutionService()
    svc.create(task_id="n1", root_task_id="root", idempotency_key="a2a-del-n1")
    svc.start("n1")
    svc.timeout("n1")  # A timed out
    # B actually completed later — must NOT flip to SUCCEEDED
    late = svc.apply_callback("n1", success=True)
    assert late.state == "TIMEOUT"
    # Recovery may retry with SAME idempotency key (no new business task)
    out = svc.recover("n1")
    assert out["action"] == "retry"
    assert out["record"]["task_id"] == "n1"
    assert out["record"]["idempotency_key"] == "a2a-del-n1"


def test_duplicate_delegation_same_idempotency_key():
    svc = ExecutionService()
    a = svc.record_delegation(
        task_id="d1",
        root_task_id="r",
        correlation_id="c",
        parent_task_id="p",
        agent_id="B",
        idempotency_key="a2a-del-dup",
    )
    b = svc.record_delegation(
        task_id="d2",
        root_task_id="r",
        correlation_id="c",
        parent_task_id="p",
        agent_id="B",
        idempotency_key="a2a-del-dup",
    )
    assert a.task_id == b.task_id


def test_concurrent_retry_single_owner():
    svc = ExecutionService()
    svc.create(task_id="own", root_task_id="own")
    svc.start("own")
    svc.timeout("own")
    t1 = svc.store.try_acquire_ownership("own")
    t2 = svc.store.try_acquire_ownership("own")
    assert t1 is not None
    assert t2 is None
    assert svc.store.release_ownership("own", t1) is True
