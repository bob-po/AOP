"""Discovery, routing preview, stats, and evaluation list routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app_context import ctx
from execution.events import (
    AGENT_DISCOVERED,
    AGENT_SELECTED,
    ExecutionEvent,
)

router = APIRouter(tags=["discovery"])


class IOModeSpec(BaseModel):
    """Input/output requirement for discovery (A2A OS)."""

    type: str | None = None
    modes: list[str] | None = None


class DiscoverRequest(BaseModel):
    """Capability-aware Agent discovery — open to any Agent (POST /v1/discover)."""

    required_skills: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    input: IOModeSpec | None = None
    output: IOModeSpec | None = None
    match_all_skills: bool = False
    exclude_agent_ids: list[str] = Field(default_factory=list)
    limit: int = 20
    # Optional lineage for Visual Runtime observation (does not affect discovery)
    root_task_id: str | None = None
    correlation_id: str | None = None
    task_id: str | None = None
    caller_agent_id: str | None = None


class RouteRequest(BaseModel):
    """Select the best Agent for a request — open to any Agent (POST /v1/route)."""

    skill: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    input: IOModeSpec | None = None
    output: IOModeSpec | None = None
    exclude_agent_ids: list[str] = Field(default_factory=list)
    root_task_id: str | None = None
    correlation_id: str | None = None
    task_id: str | None = None
    caller_agent_id: str | None = None


def _io_spec(spec: IOModeSpec | None) -> dict[str, Any]:
    if spec is None:
        return {}
    out: dict[str, Any] = {}
    if spec.type:
        out["type"] = spec.type
    if spec.modes:
        out["modes"] = spec.modes
    return out


@router.get("/v1/stats/overview")
def stats_overview() -> dict[str, Any]:
    return ctx.tasks.overview()


@router.get("/v1/stats/agents")
def stats_agents(limit: int = 50) -> dict[str, Any]:
    return {"agents": ctx.tasks.agent_performance(limit=limit)}


@router.get("/v1/router/preview")
def router_preview(skill: str) -> dict[str, Any]:
    skill = (skill or "").strip()
    if not skill:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "skill query required"},
        )
    try:
        return ctx.tasks.router_preview(skill)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"code": "router_error", "message": str(exc)},
        ) from exc


@router.get("/v1/evaluations/overview")
def evaluations_overview() -> dict[str, Any]:
    return ctx.tasks.evaluation_overview()


@router.get("/v1/evaluations")
def list_evaluations(
    limit: int = 50,
    min_score: float | None = None,
) -> dict[str, Any]:
    return {
        "evaluations": ctx.tasks.list_evaluations(limit=limit, min_score=min_score),
    }


def _emit_observation(
    event_type: str,
    *,
    root_task_id: str | None,
    correlation_id: str | None,
    task_id: str | None,
    agent_id: str | None = None,
    parent_agent_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Best-effort Visual Runtime observation — never fails the request path."""
    if not root_task_id and not task_id:
        return
    try:
        ctx.execution.events.emit(
            ExecutionEvent(
                event_type=event_type,
                root_task_id=root_task_id or task_id,
                correlation_id=correlation_id or root_task_id or task_id,
                task_id=task_id or root_task_id,
                agent_id=agent_id,
                parent_agent_id=parent_agent_id,
                payload=dict(payload or {}),
            )
        )
    except Exception:  # noqa: BLE001
        pass


@router.post("/v1/discover")
def discover_agents(body: DiscoverRequest) -> dict[str, Any]:
    """A2A OS: capability-aware Agent discovery, open to any Agent."""
    try:
        result = ctx.tasks.discover(
            required_skills=body.required_skills,
            capabilities=body.capabilities,
            input=_io_spec(body.input),
            output=_io_spec(body.output),
            match_all_skills=body.match_all_skills,
            exclude_agent_ids=body.exclude_agent_ids,
            limit=body.limit,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"code": "discovery_error", "message": str(exc)},
        ) from exc

    agents = result.get("agents") or result.get("candidates") or []
    agent_ids = []
    for a in agents:
        if isinstance(a, dict):
            aid = a.get("agent_id") or a.get("id") or a.get("agent_key")
            if aid:
                agent_ids.append(str(aid))
    for aid in agent_ids[:20]:
        _emit_observation(
            AGENT_DISCOVERED,
            root_task_id=body.root_task_id,
            correlation_id=body.correlation_id,
            task_id=body.task_id or body.root_task_id,
            agent_id=aid,
            parent_agent_id=body.caller_agent_id,
            payload={
                "required_skills": body.required_skills,
                "discovered_count": len(agent_ids),
            },
        )
    return result


@router.post("/v1/route")
def route_request(body: RouteRequest) -> dict[str, Any]:
    """A2A OS: select the best Agent for a request, open to any Agent."""
    try:
        result = ctx.tasks.route(
            skill=body.skill,
            required_skills=body.required_skills,
            capabilities=body.capabilities,
            input=_io_spec(body.input),
            output=_io_spec(body.output),
            exclude_agent_ids=body.exclude_agent_ids,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"code": "router_error", "message": str(exc)},
        ) from exc

    # Router returns selected_agent (dict) or selected (agent_id string)
    selected = (
        result.get("selected_agent")
        or result.get("agent")
        or result.get("selected")
        or {}
    )
    if isinstance(selected, dict):
        aid = selected.get("agent_id") or selected.get("id") or selected.get("agent_key")
    elif isinstance(selected, str) and selected.strip():
        aid = selected.strip()
    else:
        aid = None
    if not aid and isinstance(result.get("agent_id"), str):
        aid = result["agent_id"]
    if aid:
        _emit_observation(
            AGENT_SELECTED,
            root_task_id=body.root_task_id,
            correlation_id=body.correlation_id,
            task_id=body.task_id or body.root_task_id,
            agent_id=str(aid),
            parent_agent_id=body.caller_agent_id,
            payload={"skill": body.skill, "score": result.get("score")},
        )
    return result
