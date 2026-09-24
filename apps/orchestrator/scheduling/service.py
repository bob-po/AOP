"""Phase 5 — SchedulingService façade for HTTP / CLI."""

from __future__ import annotations

from typing import Any, Optional

from scheduling.budget import BudgetService
from scheduling.capability import Requirement
from scheduling.context import TenantContext, get_tenant_context
from scheduling.cost import CostService
from scheduling.policy_layers import LayeredPolicyEngine, SchedulingPolicyDoc
from scheduling.reliability import ReliabilityService
from scheduling.resource import ResourceService
from scheduling.reselection import classify_failure, plan_recovery
from scheduling.selector import IntelligentScheduler, ScheduleDecision
from scheduling.simulator import simulate


class SchedulingService:
    def __init__(
        self,
        *,
        cost: CostService | None = None,
        budget: BudgetService | None = None,
        reliability: ReliabilityService | None = None,
        resources: ResourceService | None = None,
        policies: LayeredPolicyEngine | None = None,
        scheduler: IntelligentScheduler | None = None,
    ):
        self.cost = cost or CostService()
        self.budget = budget or BudgetService()
        self.reliability = reliability or ReliabilityService()
        self.resources = resources or ResourceService()
        self.policies = policies or LayeredPolicyEngine()
        self.scheduler = scheduler or IntelligentScheduler(reliability=self.reliability)

    def candidates(
        self,
        agents: list[dict[str, Any]],
        *,
        requirement: dict[str, Any] | None = None,
        exclude_agent_ids: list[str] | None = None,
        ctx: TenantContext | None = None,
    ) -> dict[str, Any]:
        ctx = ctx or get_tenant_context()
        sched_pol, _ = self.policies.resolve(tenant_id=ctx.tenant_id)
        req = Requirement.from_dict(requirement or {})
        if sched_pol.require_gpu:
            req.require_gpu = True
        if sched_pol.require_streaming:
            req.require_streaming = True
        decision = self.scheduler.select(
            agents,
            requirement=req,
            exclude_agent_ids=exclude_agent_ids,
            max_cost=sched_pol.max_cost,
            max_latency_ms=sched_pol.max_latency_ms,
            task_priority=ctx.priority or sched_pol.priority,
            tenant_weight=sched_pol.tenant_weight,
        )
        return {
            "candidates": decision.candidates,
            "excluded": decision.excluded,
            "count": len(decision.candidates),
            "tenant_id": ctx.tenant_id,
        }

    def preview(
        self,
        agents: list[dict[str, Any]],
        *,
        requirement: dict[str, Any] | None = None,
        exclude_agent_ids: list[str] | None = None,
        estimated_cost: float = 0.1,
        ctx: TenantContext | None = None,
    ) -> dict[str, Any]:
        ctx = ctx or get_tenant_context()
        budget_check = self.budget.check(estimated_cost, ctx=ctx)
        decision = self._select(agents, requirement, exclude_agent_ids, ctx)
        return {
            "preview": True,
            "decision": decision.to_dict(),
            "budget": budget_check,
            "tenant_id": ctx.tenant_id,
        }

    def select(
        self,
        agents: list[dict[str, Any]],
        *,
        requirement: dict[str, Any] | None = None,
        exclude_agent_ids: list[str] | None = None,
        estimated_cost: float = 0.1,
        ctx: TenantContext | None = None,
        commit_budget: bool = False,
    ) -> dict[str, Any]:
        ctx = ctx or get_tenant_context()
        budget_check = self.budget.check(estimated_cost, ctx=ctx)
        if not budget_check.get("allowed"):
            return {
                "selected": None,
                "budget": budget_check,
                "reason": "budget_exceeded",
                "tenant_id": ctx.tenant_id,
            }
        decision = self._select(agents, requirement, exclude_agent_ids, ctx)
        if commit_budget and decision.selected:
            self.budget.record_spend(
                estimated_cost, tenant_id=ctx.tenant_id, task_id=None
            )
        return {
            "selected": decision.selected,
            "decision": decision.to_dict(),
            "budget": budget_check,
            "tenant_id": ctx.tenant_id,
        }

    def recovery_plan(
        self,
        *,
        error_code: str | None = None,
        error: str | None = None,
        agent_id: str | None = None,
        agent_state: str | None = None,
        exclude_agent_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        klass = classify_failure(
            error_code=error_code, error=error, agent_state=agent_state
        )
        return plan_recovery(
            klass, failed_agent_id=agent_id, exclude_agent_ids=exclude_agent_ids
        )

    def simulate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return simulate(payload)

    def _select(
        self,
        agents: list[dict[str, Any]],
        requirement: dict[str, Any] | None,
        exclude_agent_ids: list[str] | None,
        ctx: TenantContext,
    ) -> ScheduleDecision:
        sched_pol, _ = self.policies.resolve(tenant_id=ctx.tenant_id)
        req = Requirement.from_dict(requirement or {})
        if sched_pol.require_gpu:
            req.require_gpu = True
        return self.scheduler.select(
            agents,
            requirement=req,
            exclude_agent_ids=exclude_agent_ids,
            max_cost=sched_pol.max_cost,
            max_latency_ms=sched_pol.max_latency_ms,
            task_priority=ctx.priority or sched_pol.priority,
            tenant_weight=sched_pol.tenant_weight,
        )


__all__ = ["SchedulingService"]
