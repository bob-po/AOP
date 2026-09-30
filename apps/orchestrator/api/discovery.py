"""Discovery, routing preview, stats, and evaluation list routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app_context import ctx

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


class RouteRequest(BaseModel):
    """Select the best Agent for a request — open to any Agent (POST /v1/route)."""

    skill: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    input: IOModeSpec | None = None
    output: IOModeSpec | None = None
    exclude_agent_ids: list[str] = Field(default_factory=list)


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


@router.post("/v1/discover")
def discover_agents(body: DiscoverRequest) -> dict[str, Any]:
    """A2A OS: capability-aware Agent discovery, open to any Agent."""
    try:
        return ctx.tasks.discover(
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


@router.post("/v1/route")
def route_request(body: RouteRequest) -> dict[str, Any]:
    """A2A OS: select the best Agent for a request, open to any Agent."""
    try:
        return ctx.tasks.route(
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
