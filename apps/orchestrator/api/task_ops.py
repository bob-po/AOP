"""Task lifecycle ops: recover, cancel, HITL, artifacts, checkpoints, evaluate."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, PlainTextResponse
from pydantic import BaseModel

from app_context import ctx
from execution import cancel_fanout
from api.runtime import collaboration_graph_payload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["task-ops"])


class HitlDecisionRequest(BaseModel):
    """HITL decision — operator Inbox or peer-agent resume."""

    node_key: str | None = None
    reason: str = "rejected by user"
    input: str | None = None
    actor: str = "system"


class NodeReplayRequest(BaseModel):
    clear_downstream: bool = True


@router.get("/v1/artifacts")
def list_artifacts_global(
    task_id: str | None = None,
    type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    try:
        items = ctx.tasks.list_all_artifacts(
            task_id=task_id, type_filter=type, limit=limit
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "storage_error", "message": str(exc)},
        ) from exc
    return {"artifacts": items}


@router.post("/v1/tasks/{task_id}/recover")
def recover_task(task_id: str) -> dict[str, Any]:
    """Phase 3: recover a stale/failed/timeout execution."""
    if ctx.execution.get(task_id) is None:
        row = ctx.tasks.get(task_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": "task not found"},
            )
        ctx.execution.create(
            task_id=task_id,
            root_task_id=task_id,
            correlation_id=task_id,
            metadata={"seeded_from": "recover"},
        )
        ctx.execution.transition(task_id, "TIMEOUT")
    try:
        return ctx.execution.recover(task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"code": "recover_error", "message": str(exc)},
        ) from exc


@router.get("/v1/tasks/{task_id}/checkpoints")
def list_task_checkpoints(
    task_id: str,
    node_key: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        items = ctx.tasks.list_checkpoints(task_id, node_key=node_key, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "checkpoint_error", "message": str(exc)},
        ) from exc
    return {"task_id": task_id, "checkpoints": items, "count": len(items)}


@router.post("/v1/tasks/{task_id}/nodes/{node_key}/replay")
def replay_task_node(
    task_id: str,
    node_key: str,
    body: NodeReplayRequest | None = None,
) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        return ctx.tasks.replay_from_node(
            task_id,
            node_key,
            clear_downstream=True if body is None else bool(body.clear_downstream),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "replay_error", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "replay_error", "message": str(exc)},
        ) from exc


@router.get("/v1/tasks/{task_id}/collaboration-graph")
def task_collaboration_graph(task_id: str) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        graph = collaboration_graph_payload(task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_graph_error", "message": str(exc)},
        ) from exc
    graph["task"] = {
        "id": row.get("id") or task_id,
        "status": row.get("status"),
        "title": row.get("title"),
        "created_at": row.get("created_at"),
    }
    return graph


@router.post("/v1/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, Any]:
    agent_endpoints: dict[str, str] = {}
    try:
        if hasattr(ctx.marketplace, "list_agents"):
            for a in ctx.marketplace.list_agents() or []:
                aid = a.get("agent_id") or a.get("id")
                ep = a.get("endpoint") or a.get("url")
                if aid and ep:
                    agent_endpoints[str(aid)] = str(ep)
    except Exception:  # noqa: BLE001
        pass

    extra_a2a_targets: list[dict[str, str]] = []
    try:
        sched = getattr(ctx.tasks, "scheduler", None)
        if sched is not None and hasattr(sched, "list_a2a_cancel_targets"):
            for item in sched.list_a2a_cancel_targets(task_id) or []:
                aid = item.get("agent_id")
                ep = agent_endpoints.get(str(aid)) if aid else None
                if not ep:
                    continue
                extra_a2a_targets.append(
                    {"endpoint": ep, "task_id": task_id, "agent_id": str(aid)}
                )
                a2a_id = item.get("a2a_task_id")
                if a2a_id and str(a2a_id) != task_id:
                    extra_a2a_targets.append(
                        {
                            "endpoint": ep,
                            "task_id": str(a2a_id),
                            "agent_id": str(aid),
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_a2a_cancel_targets skipped: %s", exc)

    row = ctx.tasks.cancel(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )

    def _a2a_cancel(endpoint: str, child_task_id: str) -> bool:
        try:
            from a2a_sdk import A2AClient

            client = A2AClient(endpoint)
            return bool(client.cancel_task(child_task_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "A2A cancel failed endpoint=%s task=%s: %s",
                endpoint,
                child_task_id,
                exc,
            )
            return False

    cascade = cancel_fanout(
        root_task_id=task_id,
        execution_service=ctx.execution,
        runtime_graph=ctx.tasks.runtime_graph,
        a2a_cancel=_a2a_cancel if (agent_endpoints or extra_a2a_targets) else None,
        agent_endpoints=agent_endpoints or None,
        extra_a2a_targets=extra_a2a_targets or None,
    )
    ctx.capacity_queue.cancel(task_id)
    out = dict(row)
    out["execution_cancel"] = cascade
    return out


@router.post("/v1/tasks/{task_id}/approve")
def approve_task(task_id: str, body: HitlDecisionRequest | None = None) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        return ctx.tasks.approve(
            task_id,
            node_key=(body.node_key if body else None),
            human_input=(body.input if body else None),
            actor=(body.actor if body else "system"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "hitl_error", "message": str(exc)},
        ) from exc


@router.post("/v1/tasks/{task_id}/reject")
def reject_task(task_id: str, body: HitlDecisionRequest | None = None) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        return ctx.tasks.reject(
            task_id,
            node_key=(body.node_key if body else None),
            reason=(body.reason if body else "rejected by user"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "hitl_error", "message": str(exc)},
        ) from exc


@router.get("/v1/tasks/{task_id}/events")
def get_events(task_id: str) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    return {"events": ctx.tasks.events(task_id)}


@router.get("/v1/tasks/{task_id}/artifacts")
def get_artifacts(task_id: str) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        artifacts = ctx.tasks.list_artifacts(task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "storage_error", "message": str(exc)},
        ) from exc
    return {"task_id": task_id, "artifacts": artifacts}


@router.get("/v1/tasks/{task_id}/package")
def download_task_package(task_id: str) -> Response:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        data = ctx.tasks.build_package(task_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "package_error", "message": str(exc)},
        ) from exc
    short = task_id.replace("-", "")[:8]
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="aop-run-{short}.zip"',
        },
    )


@router.get("/v1/tasks/{task_id}/report")
def download_task_report(task_id: str) -> PlainTextResponse:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    try:
        md = ctx.tasks.run_report_markdown(task_id)
    except KeyError:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        ) from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "package_error", "message": str(exc)},
        ) from exc
    return PlainTextResponse(md, media_type="text/markdown; charset=utf-8")


@router.get("/v1/tasks/{task_id}/evaluation")
def get_task_evaluation(task_id: str) -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    ev = ctx.tasks.get_evaluation(task_id)
    if not ev:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "evaluation not found"},
        )
    return ev


@router.post("/v1/tasks/{task_id}/evaluate")
def evaluate_task(task_id: str, method: str = "heuristic") -> dict[str, Any]:
    row = ctx.tasks.get(task_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "task not found"}
        )
    if row.get("status") not in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_terminal",
                "message": f"task status={row.get('status')} is not terminal",
            },
        )
    try:
        return ctx.tasks.evaluate(task_id, method=method or "heuristic")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc
