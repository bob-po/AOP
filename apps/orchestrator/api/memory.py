"""Task and tenant memory HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app_context import ctx

router = APIRouter(tags=["memory"])


class MemoryPutRequest(BaseModel):
    memory_key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantMemoryPutRequest(BaseModel):
    memory_key: str
    content: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@router.get("/v1/tasks/{task_id}/memory")
def get_task_memory(task_id: str) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    return {"task_id": task_id, "memories": ctx.tasks.list_memory(task_id)}


@router.put("/v1/tasks/{task_id}/memory")
def put_task_memory(task_id: str, body: MemoryPutRequest) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        return ctx.tasks.put_memory(
            task_id,
            body.memory_key,
            body.content,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc


@router.delete("/v1/tasks/{task_id}/memory/{memory_key}")
def delete_task_memory(task_id: str, memory_key: str) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    ok = ctx.tasks.delete_memory(task_id, memory_key)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "memory key not found"},
        )
    return {"deleted": True, "task_id": task_id, "memory_key": memory_key}


@router.get("/v1/memory")
def list_tenant_memory(limit: int = 50) -> dict[str, Any]:
    return {"memories": ctx.tasks.list_tenant_memory(limit=limit)}


@router.put("/v1/memory")
def put_tenant_memory(body: TenantMemoryPutRequest) -> dict[str, Any]:
    try:
        return ctx.tasks.put_tenant_memory(
            body.memory_key,
            body.content,
            title=body.title,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc


@router.get("/v1/memory/search")
def search_tenant_memory(q: str, top_k: int = 5) -> dict[str, Any]:
    query = (q or "").strip()
    if not query:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "q is required"},
        )
    return {"query": query, "hits": ctx.tasks.search_tenant_memory(query, top_k=top_k)}


@router.delete("/v1/memory/{memory_key}")
def delete_tenant_memory(memory_key: str) -> dict[str, Any]:
    ok = ctx.tasks.delete_tenant_memory(memory_key)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "memory key not found"},
        )
    return {"deleted": True, "memory_key": memory_key}


@router.post("/v1/tasks/{task_id}/memory/promote")
def promote_task_memory(task_id: str) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    written = ctx.tasks.promote_task_memory(task_id)
    return {"task_id": task_id, "promoted": len(written), "memories": written}
