"""Core task CRUD routes (extracted from main)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app_context import (
    ctx,
    forbid_cross_tenant,
    resource_tenant_from_execution,
    tenant_from_request,
)
from quota import QuotaExceeded

router = APIRouter(tags=["tasks"])


class TaskInput(BaseModel):
    type: str = "text"
    content: str = ""


class CreateTaskRequest(BaseModel):
    title: str | None = None
    input: TaskInput = Field(default_factory=TaskInput)


@router.get("/v1/tasks")
def list_tasks(
    request: Request, status: str | None = None, limit: int = 50
) -> dict[str, Any]:
    ten = tenant_from_request(request)
    return {
        "tasks": ctx.tasks.list(status=status, limit=limit, tenant_id=ten.tenant_id),
    }


@router.post("/v1/tasks", status_code=201)
def create_task(body: CreateTaskRequest, request: Request) -> dict[str, Any]:
    content = (body.input.content or "").strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "input.content required"},
        )
    ten = tenant_from_request(request)
    try:
        return ctx.tasks.create(content, title=body.title, tenant_id=ten.tenant_id)
    except QuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": exc.code,
                "message": exc.message,
                "quota": exc.snapshot,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc


@router.get("/v1/tasks/{task_id}")
def get_task(
    task_id: str, request: Request, include_graph: bool = False
) -> dict[str, Any]:
    ten = tenant_from_request(request)
    if include_graph:
        row = ctx.tasks.get_with_graph(task_id, tenant_id=ten.tenant_id)
    else:
        row = ctx.tasks.get(task_id, tenant_id=ten.tenant_id)
    if not row:
        row = (
            ctx.tasks.get_with_graph(task_id)
            if include_graph
            else ctx.tasks.get(task_id)
        )
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "task not found"},
            )
        forbid_cross_tenant(request, row.get("tenant_id"))
    try:
        row = dict(row)
        row["execution"] = ctx.execution.get_execution_view(task_id)
    except Exception:  # noqa: BLE001
        pass
    return row


@router.get("/v1/tasks/{task_id}/execution")
def get_task_execution(task_id: str, request: Request) -> dict[str, Any]:
    forbid_cross_tenant(request, resource_tenant_from_execution(task_id))
    view = ctx.execution.get_execution_view(task_id)
    if not view.get("execute") and not view.get("delegate"):
        row = ctx.tasks.get(task_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "task not found"},
            )
    return view
