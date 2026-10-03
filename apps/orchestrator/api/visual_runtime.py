"""Visual Runtime APIs — graph snapshot, event stream, control (observation layer)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app_context import (
    ctx,
    forbid_cross_tenant,
    resource_tenant_from_execution,
)
from api.runtime import collaboration_graph_payload, _json_safe
from visual_runtime import (
    merge_task_scheduler_events,
    normalize_event,
    project_visual_graph,
    synthesize_from_collaboration,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["visual-runtime"])


def _collect_visual_events(
    *,
    root: str,
    task_id: str,
    row: dict[str, Any],
    collab: dict[str, Any],
) -> list[dict[str, Any]]:
    """Prefer live EventBus; fall back to durable edges + task_events."""
    events = ctx.execution.events.list_for_root(root)
    if not events:
        events = ctx.execution.events.list_for_task(task_id)
    if events:
        return events

    try:
        sched_events = ctx.tasks.events(task_id) or []
    except Exception:  # noqa: BLE001
        sched_events = []

    # Collaboration edges → agent hop timeline (always useful after restart)
    synth = synthesize_from_collaboration(
        root_task_id=root,
        collaboration_graph=collab,
        task_row=row,
    )
    if not sched_events:
        return synth

    # Scheduler owns task.* lifecycle; keep only agent.* hops from synth to avoid dupes
    agent_hops = [
        e
        for e in synth
        if str(e.get("event_type") or "").startswith("agent.")
    ]
    return merge_task_scheduler_events(
        root_task_id=root,
        task_events=sched_events,
        base=agent_hops,
    )


def _build_task_graph(task_id: str) -> dict[str, Any]:
    try:
        row = ctx.tasks.get(task_id)
    except Exception as exc:  # noqa: BLE001 - invalid UUID / DB cast errors
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "task not found"},
        ) from exc
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    root = str(row.get("id") or task_id)
    try:
        collab = collaboration_graph_payload(root)
    except Exception:  # noqa: BLE001
        collab = {"nodes": [], "links": []}
    events = _collect_visual_events(root=root, task_id=task_id, row=row, collab=collab)
    try:
        execution_view = ctx.execution.get_execution_view(task_id)
    except Exception:  # noqa: BLE001
        execution_view = None
    snapshot = project_visual_graph(
        task_id=root,
        events=events,
        collaboration_graph=collab,
        execution_view=execution_view,
        task_row=row,
    )
    # Surface task timestamps for UI duration (no fabricated clocks)
    meta = snapshot.setdefault("task", {})
    meta["created_at"] = row.get("created_at")
    meta["updated_at"] = row.get("updated_at")
    meta["finished_at"] = (
        row.get("finished_at") or row.get("completed_at") or row.get("updated_at")
    )
    meta["status"] = row.get("status")
    return _json_safe(snapshot)


@router.get("/v1/tasks/{task_id}/graph")
def get_task_visual_graph(task_id: str, request: Request) -> dict[str, Any]:
    """Visual Runtime graph snapshot: nodes + edges + events + sequence."""
    try:
        forbid_cross_tenant(request, resource_tenant_from_execution(task_id))
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - no execution row / bad id
        pass
    return _build_task_graph(task_id)


@router.get("/v1/tasks/{task_id}/visual-events")
def get_task_visual_events(task_id: str, request: Request) -> dict[str, Any]:
    """Normalized Visual Runtime event timeline (same source as graph)."""
    forbid_cross_tenant(request, resource_tenant_from_execution(task_id))
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    root = str(row.get("id") or task_id)
    try:
        collab = collaboration_graph_payload(root)
    except Exception:  # noqa: BLE001
        collab = {"nodes": [], "links": []}
    raw = _collect_visual_events(root=root, task_id=task_id, row=row, collab=collab)
    events = [normalize_event(e) for e in raw]
    events.sort(
        key=lambda e: (
            e.get("sequence") is None,
            e.get("sequence") or 0,
            str(e.get("timestamp") or ""),
        )
    )
    return {
        "task_id": task_id,
        "root_task_id": root,
        "events": events,
        "count": len(events),
        "sequence": max((e.get("sequence") or 0) for e in events) if events else 0,
    }


@router.post("/v1/tasks/{task_id}/pause")
def pause_task(task_id: str, request: Request) -> dict[str, Any]:
    """Pause execution via existing state machine (RUNNING/PENDING → WAITING)."""
    forbid_cross_tenant(request, resource_tenant_from_execution(task_id))
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        rec = ctx.execution.transition(task_id, "WAITING")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=409,
            detail={"code": "pause_error", "message": str(exc)},
        ) from exc
    ctx.execution.events.emit(
        {
            "event_type": "agent.waiting",
            "task_id": task_id,
            "root_task_id": rec.root_task_id or task_id,
            "correlation_id": rec.correlation_id,
            "agent_id": rec.agent_id,
            "payload": {"reason": "pause", "state": rec.state},
        }
    )
    return {"task_id": task_id, "paused": True, "execution": rec.to_dict()}


@router.post("/v1/tasks/{task_id}/resume")
def resume_task(task_id: str, request: Request) -> dict[str, Any]:
    """Resume paused execution (WAITING → RUNNING) or HITL approve fallback."""
    forbid_cross_tenant(request, resource_tenant_from_execution(task_id))
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    # Prefer execution-plane resume
    try:
        rec = ctx.execution.get(task_id)
        if rec and str(rec.state).upper() == "WAITING":
            rec = ctx.execution.transition(task_id, "RUNNING")
            ctx.execution.events.emit(
                {
                    "event_type": "agent.recovered",
                    "task_id": task_id,
                    "root_task_id": rec.root_task_id or task_id,
                    "correlation_id": rec.correlation_id,
                    "agent_id": rec.agent_id,
                    "payload": {"reason": "resume", "state": rec.state},
                }
            )
            return {"task_id": task_id, "resumed": True, "execution": rec.to_dict()}
    except Exception as exc:  # noqa: BLE001
        logger.debug("execution resume skipped: %s", exc)

    # HITL plane (waiting_for_user)
    if str(row.get("status") or "") == "waiting_for_user":
        try:
            approved = ctx.tasks.approve(task_id)
            return {"task_id": task_id, "resumed": True, "hitl": approved}
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=409,
                detail={"code": "resume_error", "message": str(exc)},
            ) from exc

    raise HTTPException(
        status_code=409,
        detail={
            "code": "resume_error",
            "message": "task is not in a resumable waiting state",
        },
    )


async def _visual_stream(websocket: WebSocket, task_id: str) -> None:
    """Shared WS handler: snapshot + incremental events + graph pushes."""
    await websocket.accept()
    root = task_id
    try:
        row = ctx.tasks.get(task_id)
        if row:
            root = str(row.get("id") or task_id)
    except Exception:  # noqa: BLE001
        pass

    snapshot: dict[str, Any] = {
        "task_id": root,
        "nodes": [],
        "edges": [],
        "events": [],
        "status": "pending",
        "sequence": 0,
    }
    try:
        snapshot = _build_task_graph(task_id)
        await websocket.send_json(
            {
                "type": "snapshot",
                "task_id": task_id,
                "root_task_id": root,
                "graph": snapshot,
                "events": snapshot.get("events") or [],
                "sequence": snapshot.get("sequence") or 0,
            }
        )
    except HTTPException as exc:
        await websocket.send_json(
            {"type": "error", "message": str(exc.detail), "code": "not_found"}
        )
        await websocket.close()
        return
    except Exception as exc:  # noqa: BLE001
        await websocket.send_json({"type": "error", "message": str(exc)})

    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
    last_seq = int(snapshot.get("sequence") or 0)

    def _hook(ev):
        rid = ev.root_task_id or ev.task_id
        if rid != root and ev.task_id != task_id:
            return
        try:
            queue.put_nowait(ev)
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
                    continue
                if event_task in done and not event_task.cancelled():
                    ev = event_task.result()
                    norm = normalize_event(ev)
                    seq = norm.get("sequence")
                    if seq is not None and seq <= last_seq:
                        # sequence recovery: skip duplicates
                        continue
                    if seq is not None:
                        last_seq = int(seq)
                    await websocket.send_json(
                        {
                            "type": "event",
                            "task_id": task_id,
                            "root_task_id": root,
                            "sequence": seq,
                            "event": norm,
                        }
                    )
                    try:
                        graph = _build_task_graph(task_id)
                        await websocket.send_json(
                            {
                                "type": "graph",
                                "task_id": task_id,
                                "root_task_id": root,
                                "graph": graph,
                                "sequence": graph.get("sequence"),
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("visual graph push skipped: %s", exc)
                if receive_task in done and not receive_task.cancelled():
                    data = receive_task.result()
                    text = data.strip().lower()
                    if text in {"ping", '{"type":"ping"}'}:
                        await websocket.send_json({"type": "pong"})
                    elif text in {"snapshot", '{"type":"snapshot"}'}:
                        graph = _build_task_graph(task_id)
                        last_seq = int(graph.get("sequence") or last_seq)
                        await websocket.send_json(
                            {
                                "type": "snapshot",
                                "task_id": task_id,
                                "root_task_id": root,
                                "graph": graph,
                                "events": graph.get("events") or [],
                                "sequence": graph.get("sequence") or 0,
                            }
                        )
            except WebSocketDisconnect:
                break
            except Exception as exc:  # noqa: BLE001
                logger.debug("visual stream error: %s", exc)
                break
    finally:
        try:
            if _hook in ctx.execution.events._hooks:
                ctx.execution.events._hooks.remove(_hook)
        except Exception:  # noqa: BLE001
            pass


@router.websocket("/ws/tasks/{task_id}")
async def visual_runtime_ws(websocket: WebSocket, task_id: str):
    """Preferred Visual Runtime stream: snapshot + incremental events."""
    await _visual_stream(websocket, task_id)


@router.websocket("/v1/tasks/{task_id}/visual/ws")
async def visual_runtime_ws_v1(websocket: WebSocket, task_id: str):
    """Gateway-friendly alias under /v1/tasks/* proxy path."""
    await _visual_stream(websocket, task_id)
