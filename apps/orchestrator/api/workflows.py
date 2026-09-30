"""Workflow CRUD and run routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app_context import ctx
from quota import QuotaExceeded

router = APIRouter(tags=["workflows"])


class TaskInput(BaseModel):
    type: str = "text"
    content: str


class CreateWorkflowRequest(BaseModel):
    name: str
    description: str = ""
    workflow_key: str | None = None
    version: str = "1.0.0"
    publish: bool = True
    dag: dict[str, Any]


class RunWorkflowRequest(BaseModel):
    input: TaskInput
    title: str | None = None


@router.get("/v1/workflows")
def list_workflows(status: str | None = None) -> dict[str, Any]:
    return {"workflows": ctx.workflows.list(status=status)}


@router.post("/v1/workflows", status_code=201)
def create_workflow(body: CreateWorkflowRequest) -> dict[str, Any]:
    try:
        return ctx.workflows.create(
            name=body.name,
            description=body.description,
            dag=body.dag,
            workflow_key=body.workflow_key,
            version=body.version,
            publish=body.publish,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc


@router.get("/v1/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> dict[str, Any]:
    row = ctx.workflows.get(workflow_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "workflow not found"},
        )
    return row


@router.post("/v1/workflows/{workflow_id}/run", status_code=201)
def run_workflow(workflow_id: str, body: RunWorkflowRequest) -> dict[str, Any]:
    try:
        return ctx.tasks.run_workflow(
            workflow_id,
            content=body.input.content,
            title=body.title,
        )
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
        msg = str(exc)
        code = "not_found" if "not found" in msg else "validation_error"
        status = 404 if code == "not_found" else 400
        raise HTTPException(
            status_code=status, detail={"code": code, "message": msg}
        ) from exc
