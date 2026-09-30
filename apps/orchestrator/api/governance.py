"""Governance check / release / denial audit HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app_context import ctx
from observability.a2a_metrics import observe_governance_denial

router = APIRouter(tags=["governance"])


class GovernanceCheckRequest(BaseModel):
    """An Agent's proposed delegation, submitted to the OS for an authoritative
    governance decision. Depth / visits are NOT trusted from the caller: the OS
    reconstructs them from its own runtime graph."""

    root_task_id: str
    caller_agent_id: str
    target_agent_id: str
    caller_task_id: str | None = None
    correlation_id: str | None = None
    tenant_id: str | None = None
    requested_units: float | None = None
    units_estimated: bool = True
    deadline: str | None = None
    claimed_depth: int | None = None


class GovernanceReleaseRequest(BaseModel):
    """Release in-flight concurrency reserved by a prior successful check."""

    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/v1/governance/check")
def governance_check(body: GovernanceCheckRequest) -> dict[str, Any]:
    """A2A OS: authoritative governance decision for a proposed Agent delegation.

    Agents call this *before* delegating. The OS decides — Agents cannot raise
    their own limits. Depth and per-Agent visit counts are reconstructed from the
    recorded runtime graph, so a caller cannot under-report lineage to bypass a
    limit. Counters (calls, budget) are DB-atomic and concurrency is Redis-atomic,
    so they hold across the multiple processes of a real Agent network.
    """
    if not body.caller_agent_id or not body.target_agent_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "validation_error",
                "message": "caller_agent_id and target_agent_id required",
            },
        )
    try:
        decision = ctx.governance.check_and_reserve(
            root_task_id=body.root_task_id,
            caller_agent_id=body.caller_agent_id,
            target_agent_id=body.target_agent_id,
            caller_task_id=body.caller_task_id,
            correlation_id=body.correlation_id,
            tenant_id=body.tenant_id,
            requested_units=body.requested_units,
            units_estimated=body.units_estimated,
            deadline=body.deadline,
            claimed_depth=body.claimed_depth,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "governance_error", "message": str(exc)},
        ) from exc
    result = decision.to_dict()
    if not result.get("allowed"):
        observe_governance_denial(result.get("code") or "UNKNOWN")
        return result
    ok, reason = ctx.agent_lifecycle.accepts_delegation(body.target_agent_id)
    if ok:
        return result
    if reason == "at_capacity" and ctx.exec_cfg.queue_enabled:
        overflow = "wait"
        try:
            from execution.policy import PolicyEngine

            pol = PolicyEngine().resolve()
            overflow = pol.capacity_overflow or "wait"
        except Exception:  # noqa: BLE001
            pass
        if overflow == "wait":
            q = ctx.capacity_queue.enqueue(
                task_id=body.caller_task_id or body.root_task_id,
                agent_id=body.target_agent_id,
                root_task_id=body.root_task_id,
                correlation_id=body.correlation_id,
            )
            if q.get("queued"):
                tid = body.caller_task_id or body.root_task_id
                try:
                    if ctx.execution.get(tid) is None:
                        ctx.execution.create(
                            task_id=tid,
                            root_task_id=body.root_task_id,
                            correlation_id=body.correlation_id or tid,
                            agent_id=body.target_agent_id,
                            metadata={"queued": True},
                        )
                    ctx.execution.transition(tid, "WAITING")
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "allowed": True,
                    "code": "QUEUED",
                    "reason": "capacity wait queue",
                    "queued": True,
                    "queue": q,
                    "context": decision.to_dict().get("context")
                    if hasattr(decision, "to_dict")
                    else result.get("context"),
                }
            observe_governance_denial("CAPACITY_QUEUE_FULL")
            return {
                "allowed": False,
                "code": "CONCURRENCY_LIMIT_EXCEEDED",
                "reason": "max_queue_depth exceeded",
                "queue": q,
                "context": {"root_task_id": body.root_task_id},
            }
    observe_governance_denial("CAPACITY" if reason == "at_capacity" else "LIFECYCLE")
    return {
        "allowed": False,
        "code": "CONCURRENCY_LIMIT_EXCEEDED"
        if reason == "at_capacity"
        else "POLICY_DISABLED",
        "reason": f"agent lifecycle rejected: {reason}",
        "context": {"root_task_id": body.root_task_id, "lifecycle_reason": reason},
    }


@router.post("/v1/governance/release")
def governance_release(body: GovernanceReleaseRequest) -> dict[str, Any]:
    """A2A OS: release in-flight concurrency reserved by a prior check."""
    try:
        ctx.governance.release(body.context)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "governance_error", "message": str(exc)},
        ) from exc
    return {"released": True}


@router.get("/v1/governance/denials")
def governance_denials(
    root_task_id: str | None = None,
    code: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """A2A OS: audit trail of governance denials (queryable from Task/Audit)."""
    try:
        items = ctx.governance.list_denials(
            root_task_id=root_task_id, code=code, limit=limit
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "governance_error", "message": str(exc)},
        ) from exc
    return {"denials": items, "count": len(items)}
