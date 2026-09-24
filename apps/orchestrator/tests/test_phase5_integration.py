"""Phase 5 — integration: cost + reselection + tenant isolation + scheduler."""

from __future__ import annotations

from execution import ExecutionService
from scheduling import (
    SchedulingService,
    TenantContext,
    assert_same_tenant,
    plan_recovery,
    classify_failure,
    set_tenant_context,
    reset_tenant_context,
)
import pytest


def test_execution_cost_on_success():
    svc = ExecutionService()
    svc.create(task_id="ic1", root_task_id="ic1", agent_id="A")
    svc.start("ic1")
    svc.succeed("ic1")
    cost = svc.cost_service.task_cost("ic1")
    assert cost["count"] >= 1


def test_retry_reselection_excludes_failed_agent():
    klass = classify_failure(error_code="TIMEOUT")
    plan = plan_recovery(klass, failed_agent_id="agent-a")
    assert plan["reselect"] is True
    sched = SchedulingService()
    agents = [
        {"agent_id": "agent-a", "skills": ["web-search"], "status": "online", "latency_ms": 50},
        {"agent_id": "agent-b", "skills": ["web-search"], "status": "online", "latency_ms": 80},
    ]
    out = sched.select(
        agents,
        requirement={"skill": "web-search"},
        exclude_agent_ids=plan["exclude_agent_ids"],
        ctx=TenantContext(),
    )
    assert out["selected"]["agent_id"] == "agent-b"


def test_budget_enforcement_blocks_select():
    sched = SchedulingService()
    sched.budget.ensure_tenant_budget("tenant-budget", daily=0.01, monthly=0.01)
    out = sched.select(
        [{"agent_id": "x", "skills": ["s"], "status": "online"}],
        requirement={"skill": "s"},
        estimated_cost=5.0,
        ctx=TenantContext(tenant_id="tenant-budget"),
    )
    assert out["selected"] is None
    assert out["reason"] == "budget_exceeded"


def test_tenant_isolation_on_assert():
    with pytest.raises(PermissionError):
        assert_same_tenant("tenant-b", ctx=TenantContext(tenant_id="tenant-a"))


def test_collaboration_cost_tree():
    svc = ExecutionService()
    token = set_tenant_context(TenantContext(tenant_id="tenant-c"))
    try:
        svc.create(task_id="root-c", root_task_id="root-c", agent_id="A")
        svc.start("root-c")
        svc.succeed("root-c")
        svc.create(task_id="child-c", root_task_id="root-c", parent_task_id="root-c", agent_id="B")
        svc.start("child-c")
        svc.succeed("child-c")
        breakdown = svc.cost_service.task_breakdown("root-c")
        assert breakdown["total"]["count"] >= 2
        assert "A" in breakdown["by_agent"] or "B" in breakdown["by_agent"]
    finally:
        reset_tenant_context(token)


def test_router_scheduler_preview_selects():
    sched = SchedulingService()
    agents = [
        {"agent_id": "a1", "skills": ["analysis"], "status": "online", "latency_ms": 200, "load": 0.2},
        {"agent_id": "a2", "skills": ["analysis"], "status": "online", "latency_ms": 2000, "load": 0.8, "queue_depth": 5},
    ]
    preview = sched.preview(agents, requirement={"skill": "analysis"}, estimated_cost=0.1)
    assert preview["decision"]["selected"]["agent_id"] == "a1"
