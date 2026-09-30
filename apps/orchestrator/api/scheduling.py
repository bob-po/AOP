"""Scheduling, cost, capacity, and tenant policy HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app_context import (
    ctx,
    forbid_cross_tenant,
    resource_tenant_from_execution,
    tenant_from_request,
)
from scheduling import reset_tenant_context, set_tenant_context

router = APIRouter(tags=["scheduling"])


class SchedulingRequest(BaseModel):
    agents: list[dict[str, Any]] = Field(default_factory=list)
    requirement: dict[str, Any] = Field(default_factory=dict)
    exclude_agent_ids: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.1
    skill: str | None = None


class TenantPolicyBody(BaseModel):
    policy: dict[str, Any] = Field(default_factory=dict)


def _agents_for_scheduling(
    body_agents: list[dict[str, Any]], skill: str | None
) -> list[dict[str, Any]]:
    if body_agents:
        return body_agents
    try:
        if skill:
            ranked = ctx.tasks.router.rank(skill)
            return [
                {
                    "agent_id": a.agent_id,
                    "agent_key": a.agent_key,
                    "name": a.name,
                    "endpoint": a.endpoint,
                    "status": a.status,
                    "skills": list(a.skills or []),
                    "priority": a.priority,
                    "latency_ms": (a.score_breakdown or {}).get("latency_ms"),
                }
                for a in ranked
            ]
    except Exception:  # noqa: BLE001
        pass
    return []


@router.get("/v1/scheduling/candidates")
def scheduling_candidates(
    request: Request,
    skill: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    ten = tenant_from_request(request)
    token = set_tenant_context(ten)
    try:
        agents = _agents_for_scheduling([], skill or None)
        return ctx.scheduling.candidates(
            agents[:limit],
            requirement={"skill": skill} if skill else {},
            ctx=ten,
        )
    finally:
        reset_tenant_context(token)


@router.post("/v1/scheduling/preview")
def scheduling_preview(body: SchedulingRequest, request: Request) -> dict[str, Any]:
    ten = tenant_from_request(request)
    token = set_tenant_context(ten)
    try:
        skill = body.skill or (body.requirement or {}).get("skill")
        agents = _agents_for_scheduling(body.agents, skill)
        req = dict(body.requirement or {})
        if skill and not req.get("skill"):
            req["skill"] = skill
        return ctx.scheduling.preview(
            agents,
            requirement=req,
            exclude_agent_ids=body.exclude_agent_ids,
            estimated_cost=body.estimated_cost,
            ctx=ten,
        )
    finally:
        reset_tenant_context(token)


@router.post("/v1/scheduling/select")
def scheduling_select(body: SchedulingRequest, request: Request) -> dict[str, Any]:
    ten = tenant_from_request(request)
    token = set_tenant_context(ten)
    try:
        skill = body.skill or (body.requirement or {}).get("skill")
        agents = _agents_for_scheduling(body.agents, skill)
        req = dict(body.requirement or {})
        if skill and not req.get("skill"):
            req["skill"] = skill
        return ctx.scheduling.select(
            agents,
            requirement=req,
            exclude_agent_ids=body.exclude_agent_ids,
            estimated_cost=body.estimated_cost,
            ctx=ten,
            commit_budget=True,
        )
    finally:
        reset_tenant_context(token)


@router.post("/v1/scheduling/simulate")
def scheduling_simulate(body: dict[str, Any]) -> dict[str, Any]:
    return ctx.scheduling.simulate(body)


@router.post("/v1/scheduling/recovery-plan")
def scheduling_recovery_plan(body: dict[str, Any]) -> dict[str, Any]:
    return ctx.scheduling.recovery_plan(
        error_code=body.get("error_code"),
        error=body.get("error"),
        agent_id=body.get("agent_id"),
        agent_state=body.get("agent_state"),
        exclude_agent_ids=body.get("exclude_agent_ids"),
    )


@router.get("/v1/agents/{agent_id}/capacity")
def agent_capacity(agent_id: str) -> dict[str, Any]:
    health = ctx.agent_lifecycle.health(agent_id)
    depth = ctx.capacity_queue.depth(agent_id)
    quota = ctx.scheduling.resources.get_quota()
    ok, reason = ctx.scheduling.resources.check_agent_capacity(
        health, queue_depth=depth, quota=quota
    )
    return {
        "agent_id": agent_id,
        "health": health,
        "queue_depth": depth,
        "quota": quota.to_dict(),
        "accepts": ok,
        "reason": reason,
    }


@router.get("/v1/agents/{agent_id}/reliability")
def agent_reliability(agent_id: str) -> dict[str, Any]:
    try:
        if hasattr(ctx.execution.store, "_by_key"):
            records = list(ctx.execution.store._by_key.values())  # type: ignore[attr-defined]
            ctx.scheduling.reliability.compute_from_records(
                [r for r in records if r.agent_id == agent_id]
            )
    except Exception:  # noqa: BLE001
        pass
    rel = ctx.scheduling.reliability.get(agent_id)
    return rel.to_dict() if rel else {
        "agent_id": agent_id,
        "sample_size": 0,
        "availability": 1.0,
        "success_rate": 0.0,
        "note": "insufficient_samples",
    }


@router.get("/v1/tasks/{task_id}/cost")
def task_cost(task_id: str, request: Request) -> dict[str, Any]:
    cost = ctx.scheduling.cost.task_cost(task_id)
    items = cost.get("items") or []
    resource_tenant = None
    for it in items:
        if it.get("tenant_id"):
            resource_tenant = str(it["tenant_id"])
            break
    if resource_tenant is None:
        resource_tenant = resource_tenant_from_execution(task_id)
    forbid_cross_tenant(request, resource_tenant)
    return cost


@router.get("/v1/tasks/{task_id}/cost/breakdown")
def task_cost_breakdown(task_id: str, request: Request) -> dict[str, Any]:
    breakdown = ctx.scheduling.cost.task_breakdown(task_id)
    items = breakdown.get("items") or []
    resource_tenant = None
    for it in items:
        if it.get("tenant_id"):
            resource_tenant = str(it["tenant_id"])
            break
    if resource_tenant is None:
        resource_tenant = resource_tenant_from_execution(task_id)
    forbid_cross_tenant(request, resource_tenant)
    return breakdown


@router.get("/v1/tenants/{tenant_id}/quota")
def tenant_quota(tenant_id: str, request: Request) -> dict[str, Any]:
    forbid_cross_tenant(request, tenant_id)
    q = ctx.scheduling.resources.get_quota(tenant_id=tenant_id)
    return q.to_dict()


@router.get("/v1/tenants/{tenant_id}/budget")
def tenant_budget(tenant_id: str, request: Request) -> dict[str, Any]:
    forbid_cross_tenant(request, tenant_id)
    budgets = ctx.scheduling.budget.ensure_tenant_budget(tenant_id)
    return {k: v.to_dict() for k, v in budgets.items()}


@router.get("/v1/tenants/{tenant_id}/cost")
def tenant_cost(tenant_id: str, request: Request) -> dict[str, Any]:
    forbid_cross_tenant(request, tenant_id)
    return ctx.scheduling.cost.tenant_cost(tenant_id)


@router.get("/v1/tenants/{tenant_id}/policy")
def get_tenant_policy(tenant_id: str, request: Request) -> dict[str, Any]:
    forbid_cross_tenant(request, tenant_id)
    return {
        "tenant_id": tenant_id,
        "policy": ctx.scheduling.policies.get_tenant_policy(tenant_id).to_dict(),
    }


@router.post("/v1/tenants/{tenant_id}/policy")
def set_tenant_policy(
    tenant_id: str, body: TenantPolicyBody, request: Request
) -> dict[str, Any]:
    forbid_cross_tenant(request, tenant_id)
    doc = ctx.scheduling.policies.set_tenant_policy(tenant_id, body.policy)
    return {"tenant_id": tenant_id, "policy": doc.to_dict()}
