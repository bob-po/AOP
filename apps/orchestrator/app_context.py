"""Shared orchestrator composition / request helpers.

Service instances are bound from ``main`` after construction so API routers
can depend on a single context instead of importing ``main`` circularly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException, Request

from scheduling import DEFAULT_TENANT_ID, TenantContext, assert_same_tenant


@dataclass
class AppContext:
    tasks: Any = None
    execution: Any = None
    marketplace: Any = None
    scheduling: Any = None
    governance: Any = None
    workflows: Any = None
    agent_lifecycle: Any = None
    capacity_queue: Any = None
    exec_cfg: Any = None


ctx = AppContext()


def bind_services(
    *,
    tasks: Any,
    execution: Any,
    marketplace: Any,
    scheduling: Any,
    governance: Any | None = None,
    workflows: Any | None = None,
    agent_lifecycle: Any | None = None,
    capacity_queue: Any | None = None,
    exec_cfg: Any | None = None,
) -> None:
    ctx.tasks = tasks
    ctx.execution = execution
    ctx.marketplace = marketplace
    ctx.scheduling = scheduling
    ctx.governance = governance
    ctx.workflows = workflows
    ctx.agent_lifecycle = agent_lifecycle
    ctx.capacity_queue = capacity_queue
    ctx.exec_cfg = exec_cfg


def tenant_from_request(request: Request) -> TenantContext:
    return TenantContext.from_headers(dict(request.headers))


def require_admin(request: Request) -> None:
    """When AOP_ADMIN_TOKEN is set, require matching X-AOP-Admin-Token."""
    expected = (os.getenv("AOP_ADMIN_TOKEN") or "").strip()
    if not expected:
        return
    got = (request.headers.get("X-AOP-Admin-Token") or "").strip()
    if got != expected:
        raise HTTPException(
            status_code=403,
            detail={"code": "admin_forbidden", "message": "admin token required"},
        )


def forbid_cross_tenant(request: Request, resource_tenant_id: str | None) -> None:
    """Non-default tenants cannot read other tenants' data."""
    ten = tenant_from_request(request)
    try:
        assert_same_tenant(resource_tenant_id or DEFAULT_TENANT_ID, ctx=ten)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "tenant_forbidden", "message": str(exc)},
        ) from exc


def resource_tenant_from_execution(task_id: str) -> Optional[str]:
    if ctx.execution is None:
        return None
    view = ctx.execution.get_execution_view(task_id)
    for key in ("execute", "delegate"):
        row = view.get(key) or {}
        if row.get("tenant_id"):
            return str(row["tenant_id"])
    return None


def resource_tenant_from_graph(root_task_id: str) -> Optional[str]:
    if ctx.tasks is None:
        return None
    try:
        edges = ctx.tasks.runtime_graph.list_edges(root_task_id)
        for e in edges or []:
            if e.get("tenant_id"):
                return str(e["tenant_id"])
    except Exception:  # noqa: BLE001
        pass
    return None


def public_base_url(request: Request) -> str:
    """Prefer reverse-proxy headers so install one-liners point at the reachable host."""
    proto = (
        request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    ).split(",")[0].strip()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    ).split(",")[0].strip()
    if not host:
        return str(request.base_url).rstrip("/")
    return f"{proto}://{host}".rstrip("/")
