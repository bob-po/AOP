"""Runtime graph and collaboration HTTP / WebSocket routes."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app_context import (
    ctx,
    forbid_cross_tenant,
    resource_tenant_from_graph,
    tenant_from_request,
)
from scheduling import DEFAULT_TENANT_ID

logger = logging.getLogger(__name__)
router = APIRouter(tags=["runtime"])


class RuntimeEdgeRequest(BaseModel):
    """An Agent-to-Agent call edge in the runtime execution graph."""

    caller_agent_id: str
    target_agent_id: str
    root_task_id: str | None = None
    parent_task_id: str | None = None
    task_id: str | None = None
    correlation_id: str | None = None
    skill: str | None = None
    depth: int = 0
    status: str = "submitted"
    tenant_id: str | None = None


def _json_safe(value: Any) -> Any:
    """Convert datetimes / nested structures for WebSocket JSON frames."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def collaboration_graph_payload(root_task_id: str) -> dict[str, Any]:
    """Build enriched collaboration graph (handoffs / artifacts / lifecycle)."""
    graph = ctx.tasks.collaboration_graph_view(root_task_id)
    for node in graph.get("nodes") or []:
        if node.get("type") == "agent":
            life = ctx.agent_lifecycle.get(node["id"])
            if life:
                node["state"] = life.get("state")
                node["active_tasks"] = life.get("active_tasks")
                node["last_seen"] = life.get("last_seen")
                node["task_count"] = life.get("active_tasks")
    return _json_safe(graph)


@router.post("/v1/runtime/edges", status_code=201)
def record_runtime_edge(body: RuntimeEdgeRequest) -> dict[str, Any]:
    """A2A OS: record an Agent-to-Agent call edge in the runtime execution graph."""
    if not body.caller_agent_id or not body.target_agent_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "validation_error",
                "message": "caller_agent_id and target_agent_id required",
            },
        )
    try:
        return ctx.tasks.record_runtime_edge(
            caller_agent_id=body.caller_agent_id,
            target_agent_id=body.target_agent_id,
            root_task_id=body.root_task_id,
            parent_task_id=body.parent_task_id,
            task_id=body.task_id,
            correlation_id=body.correlation_id,
            skill=body.skill,
            depth=body.depth,
            status=body.status,
            tenant_id=body.tenant_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_graph_error", "message": str(exc)},
        ) from exc


@router.get("/v1/runtime/graph/{root_task_id}")
def runtime_graph(root_task_id: str) -> dict[str, Any]:
    """Raw runtime edge list for a root task (debug / lineage)."""
    try:
        return ctx.tasks.runtime_graph_view(root_task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_graph_error", "message": str(exc)},
        ) from exc


@router.get("/v1/collaboration/graph/{root_task_id}")
def collaboration_graph(root_task_id: str, request: Request) -> dict[str, Any]:
    """Canonical collaboration graph for Console (nodes + links + tree + lifecycle)."""
    forbid_cross_tenant(request, resource_tenant_from_graph(root_task_id))
    try:
        return collaboration_graph_payload(root_task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_graph_error", "message": str(exc)},
        ) from exc


@router.get("/v1/collaboration/events/{root_task_id}")
def collaboration_events(root_task_id: str, request: Request) -> dict[str, Any]:
    """Phase 3: ordered execution events for a collaboration root."""
    forbid_cross_tenant(request, resource_tenant_from_graph(root_task_id))
    items = ctx.execution.events.list_for_root(root_task_id)
    ten = tenant_from_request(request)
    if ten.tenant_id != DEFAULT_TENANT_ID:
        items = [
            e
            for e in items
            if not (e.get("payload") or {}).get("tenant_id")
            or str((e.get("payload") or {}).get("tenant_id")) == ten.tenant_id
        ]
    return {"root_task_id": root_task_id, "events": items, "count": len(items)}


@router.websocket("/v1/collaboration/stream/{root_task_id}")
async def collaboration_stream(websocket: WebSocket, root_task_id: str):
    """P4.16: realtime collaboration events + graph snapshots (handoff/artifacts)."""
    await websocket.accept()

    async def _push_graph() -> None:
        try:
            graph = collaboration_graph_payload(root_task_id)
            await websocket.send_json(
                {
                    "type": "graph",
                    "root_task_id": root_task_id,
                    "graph": graph,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("collaboration graph push skipped: %s", exc)

    try:
        snapshot = ctx.execution.events.list_for_root(root_task_id)
        await websocket.send_json(
            {
                "type": "snapshot",
                "root_task_id": root_task_id,
                "events": snapshot,
                "count": len(snapshot),
            }
        )
    except Exception as exc:  # noqa: BLE001
        await websocket.send_json({"type": "error", "message": str(exc)})
    await _push_graph()

    queue: asyncio.Queue = asyncio.Queue(maxsize=256)

    def _hook(ev):
        if ev.root_task_id != root_task_id:
            return
        try:
            queue.put_nowait(ev.to_dict())
        except asyncio.QueueFull:
            pass

    ctx.execution.events.on_emit(_hook)
    try:
        while True:
            try:
                receive_task = asyncio.create_task(websocket.receive_text())
                event_task = asyncio.create_task(queue.get())
                done, pending = await asyncio.wait(
                    {receive_task, event_task},
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=30.0,
                )
                for t in pending:
                    t.cancel()
                if not done:
                    await websocket.send_json({"type": "ping"})
                    await _push_graph()
                    continue
                if event_task in done and not event_task.cancelled():
                    payload = event_task.result()
                    await websocket.send_json(
                        {
                            "type": "event",
                            "root_task_id": root_task_id,
                            "sequence": (payload.get("payload") or {}).get("sequence"),
                            "event": payload,
                        }
                    )
                    await _push_graph()
                if receive_task in done and not receive_task.cancelled():
                    data = receive_task.result()
                    if data.strip().lower() in {"ping", '{"type":"ping"}'}:
                        await websocket.send_json({"type": "pong"})
            except WebSocketDisconnect:
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("collaboration stream error: %s", exc)
                break
    finally:
        try:
            if _hook in ctx.execution.events._hooks:
                ctx.execution.events._hooks.remove(_hook)
        except Exception:  # noqa: BLE001
            pass
