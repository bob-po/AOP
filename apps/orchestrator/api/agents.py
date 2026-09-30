"""Agent lifecycle / runtime health routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app_context import ctx
from execution.state_machine import IllegalTransition

router = APIRouter(tags=["agents"])


class AgentHeartbeatRequest(BaseModel):
    active_tasks: int | None = None
    load: float | None = None
    version: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


@router.get("/v1/agents/{agent_id}/health")
@router.get("/v1/agent-runtime/{agent_id}/health")
def agent_health(agent_id: str) -> dict[str, Any]:
    """Lifecycle health. Prefer ``/v1/agent-runtime/...``; ``/v1/agents/...`` kept for Gateway GET proxy."""
    return ctx.agent_lifecycle.health(agent_id)


@router.post("/v1/agent-runtime/{agent_id}/heartbeat")
def agent_heartbeat(
    agent_id: str, body: AgentHeartbeatRequest | None = None
) -> dict[str, Any]:
    body = body or AgentHeartbeatRequest()
    rec = ctx.agent_lifecycle.heartbeat(
        agent_id,
        active_tasks=body.active_tasks,
        load=body.load,
        version=body.version,
        capabilities=body.capabilities or None,
    )
    return rec.to_dict()


@router.post("/v1/agent-runtime/{agent_id}/drain")
def agent_drain(agent_id: str) -> dict[str, Any]:
    """Stop accepting new work; finish in-flight then OFFLINE."""
    try:
        if ctx.agent_lifecycle.get(agent_id) is None:
            ctx.agent_lifecycle.register(agent_id)
            ctx.agent_lifecycle.mark_ready(agent_id)
        rec = ctx.agent_lifecycle.drain(agent_id)
    except (KeyError, IllegalTransition) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "lifecycle_error", "message": str(exc)},
        ) from exc
    return rec.to_dict()
