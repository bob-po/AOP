"""Orchestrator HTTP API (Tasks + Artifacts + Workflows)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from service import TaskService
from workflows import WorkflowService
from marketplace import MarketplaceService
from health_monitor import HealthMonitor
from observability import start_metrics_server, get_metrics_text
from websocket import manager as websocket_manager
from streams import StreamClient
from quota import QuotaExceeded
from billing.stripe_checkout import StripeCheckoutError
from billing.webhook import WebhookError

# OpenTelemetry tracing
try:
    from tracing import instrument_fastapi, ensure_tracing_initialized
    ensure_tracing_initialized()
    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False

logger = logging.getLogger(__name__)

app = FastAPI(title="AOP Orchestrator", version="0.16.0")
tasks = TaskService()
workflows = WorkflowService()
marketplace = MarketplaceService()
streams = StreamClient()

# Instrument FastAPI for tracing
if TRACING_AVAILABLE:
    instrument_fastapi(app)


class TaskInput(BaseModel):
    type: str = "text"
    content: str


class CreateTaskRequest(BaseModel):
    input: TaskInput
    title: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


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


class HitlDecisionRequest(BaseModel):
    node_key: str | None = None
    reason: str = "rejected by user"


class MemoryPutRequest(BaseModel):
    memory_key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantMemoryPutRequest(BaseModel):
    memory_key: str
    content: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "orchestrator", "phase": "20-tenant-memory"}


@app.get("/v1/metrics")
def metrics_json(hours: float = 24, format: str = "json") -> Any:
    if (format or "json").lower() in {"prom", "prometheus", "text"}:
        # Combine both metrics sources
        observability_metrics = tasks.metrics_prometheus(hours=hours)
        prometheus_metrics = get_metrics_text()
        combined_metrics = f"{observability_metrics}\n{prometheus_metrics}"
        return Response(
            content=combined_metrics,
            media_type="text/plain; version=0.0.4",
        )
    return tasks.metrics_snapshot(hours=hours)

@app.get("/metrics")
def prometheus_metrics() -> Response:
    """Native Prometheus metrics endpoint for scraping."""
    prometheus_metrics = get_metrics_text()
    return Response(
        content=prometheus_metrics,
        media_type="text/plain; version=0.0.4",
    )


@app.get("/v1/stats/overview")
def stats_overview() -> dict[str, Any]:
    return tasks.overview()


@app.get("/v1/stats/agents")
def stats_agents(limit: int = 50) -> dict[str, Any]:
    return {"agents": tasks.agent_performance(limit=limit)}


@app.get("/v1/billing/usage")
def billing_usage(days: int = 30) -> dict[str, Any]:
    try:
        return tasks.billing_usage(days=days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "billing_error", "message": str(exc)},
        ) from exc


@app.get("/v1/billing/summary")
def billing_summary() -> dict[str, Any]:
    try:
        return tasks.billing_summary()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "billing_error", "message": str(exc)},
        ) from exc


@app.get("/v1/billing/invoice")
def billing_invoice_preview(days: int = 30) -> dict[str, Any]:
    try:
        return tasks.invoice_preview(days=days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "invoice_error", "message": str(exc)},
        ) from exc


@app.get("/v1/billing/invoice.md")
def billing_invoice_markdown(days: int = 30) -> Response:
    try:
        text = tasks.invoice_preview_markdown(days=days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "invoice_error", "message": str(exc)},
        ) from exc
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="invoice-preview.md"'},
    )


class CreateInvoiceRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=366)
    status: str = "draft"


@app.post("/v1/billing/invoices", status_code=201)
def billing_invoice_create(body: CreateInvoiceRequest) -> dict[str, Any]:
    try:
        return tasks.create_invoice(days=body.days, status=body.status)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "invoice_error", "message": str(exc)},
        ) from exc


@app.get("/v1/billing/invoices")
def billing_invoice_list(limit: int = 50) -> dict[str, Any]:
    try:
        return {"invoices": tasks.list_invoices(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "invoice_error", "message": str(exc)},
        ) from exc


@app.get("/v1/billing/invoices/{invoice_id}")
def billing_invoice_get(invoice_id: str) -> dict[str, Any]:
    row = tasks.get_invoice(invoice_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "invoice not found"},
        )
    return row


class CheckoutRequest(BaseModel):
    dry_run: bool | None = None


@app.post("/v1/billing/invoices/{invoice_id}/checkout", status_code=201)
def billing_invoice_checkout(
    invoice_id: str, body: CheckoutRequest | None = None
) -> dict[str, Any]:
    try:
        return tasks.create_checkout(
            invoice_id,
            dry_run=None if body is None else body.dry_run,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": str(exc)},
        ) from exc
    except (ValueError, StripeCheckoutError) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "checkout_error", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "checkout_error", "message": str(exc)},
        ) from exc


@app.get("/v1/billing/checkouts")
def billing_checkout_list(limit: int = 20) -> dict[str, Any]:
    try:
        return {"checkouts": tasks.list_checkouts(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "checkout_error", "message": str(exc)},
        ) from exc


@app.post("/v1/billing/webhooks/stripe")
async def billing_stripe_webhook(request: Request) -> dict[str, Any]:
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature")
    try:
        return tasks.handle_stripe_webhook(payload, sig)
    except WebhookError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "webhook_error", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "webhook_error", "message": str(exc)},
        ) from exc


class SimulatePaidRequest(BaseModel):
    stripe_session_id: str


@app.post("/v1/billing/checkouts/simulate-paid")
def billing_simulate_paid(body: SimulatePaidRequest) -> dict[str, Any]:
    try:
        return tasks.simulate_checkout_paid(body.stripe_session_id.strip())
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "forbidden", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "webhook_error", "message": str(exc)},
        ) from exc


@app.get("/v1/quotas")
def quotas_status() -> dict[str, Any]:
    try:
        return tasks.quota_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "quota_error", "message": str(exc)},
        ) from exc


@app.get("/v1/quotas/grants")
def quotas_grants(limit: int = 20) -> dict[str, Any]:
    try:
        return {"grants": tasks.list_quota_grants(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "quota_error", "message": str(exc)},
        ) from exc


class QuotaUpdateRequest(BaseModel):
    max_tasks_per_day: int | None = None
    max_agent_runs_per_day: int | None = None
    max_concurrent_tasks: int | None = None
    max_estimated_usd_per_month: float | None = None
    enabled: bool | None = None


@app.put("/v1/quotas")
def quotas_update(body: QuotaUpdateRequest) -> dict[str, Any]:
    try:
        return tasks.update_quota(**body.model_dump(exclude_none=True))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "quota_error", "message": str(exc)},
        ) from exc


@app.get("/v1/egress")
def egress_get() -> dict[str, Any]:
    try:
        return tasks.egress_policy()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "egress_error", "message": str(exc)},
        ) from exc


class EgressUpdateRequest(BaseModel):
    mode: str | None = None
    patterns: str | None = None
    enabled: bool | None = None


@app.put("/v1/egress")
def egress_update(body: EgressUpdateRequest) -> dict[str, Any]:
    try:
        return tasks.update_egress(**body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "egress_error", "message": str(exc)},
        ) from exc


@app.get("/v1/egress/check")
def egress_check(url: str) -> dict[str, Any]:
    url = (url or "").strip()
    if not url:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "url query required"},
        )
    try:
        return tasks.check_egress(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={"code": "egress_error", "message": str(exc)},
        ) from exc


@app.get("/v1/router/preview")
def router_preview(skill: str) -> dict[str, Any]:
    skill = (skill or "").strip()
    if not skill:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "skill query required"},
        )
    try:
        return tasks.router_preview(skill)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"code": "router_error", "message": str(exc)},
        ) from exc


@app.get("/v1/evaluations/overview")
def evaluations_overview() -> dict[str, Any]:
    return tasks.evaluation_overview()


@app.get("/v1/evaluations")
def list_evaluations(
    limit: int = 50,
    min_score: float | None = None,
) -> dict[str, Any]:
    return {
        "evaluations": tasks.list_evaluations(limit=limit, min_score=min_score),
    }


@app.get("/v1/artifacts")
def list_artifacts_global(
    task_id: str | None = None,
    type: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    try:
        items = tasks.list_all_artifacts(task_id=task_id, type_filter=type, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "storage_error", "message": str(exc)},
        ) from exc
    return {"artifacts": items}


@app.get("/v1/tasks")
def list_tasks(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {"tasks": tasks.list(status=status, limit=limit)}


@app.post("/v1/tasks", status_code=201)
def create_task(body: CreateTaskRequest) -> dict[str, Any]:
    content = (body.input.content or "").strip()
    if not content:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "input.content required"},
        )
    try:
        return tasks.create(content, title=body.title)
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


@app.get("/v1/tasks/{task_id}")
def get_task(task_id: str) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    return row


@app.post("/v1/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, Any]:
    row = tasks.cancel(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    return row


@app.post("/v1/tasks/{task_id}/approve")
def approve_task(task_id: str, body: HitlDecisionRequest | None = None) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        return tasks.approve(task_id, node_key=(body.node_key if body else None))
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "hitl_error", "message": str(exc)},
        ) from exc


@app.post("/v1/tasks/{task_id}/reject")
def reject_task(task_id: str, body: HitlDecisionRequest | None = None) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        return tasks.reject(
            task_id,
            node_key=(body.node_key if body else None),
            reason=(body.reason if body else "rejected by user"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "hitl_error", "message": str(exc)},
        ) from exc


@app.get("/v1/tasks/{task_id}/events")
def get_events(task_id: str) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    return {"events": tasks.events(task_id)}


@app.get("/v1/tasks/{task_id}/artifacts")
def get_artifacts(task_id: str) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        artifacts = tasks.list_artifacts(task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail={"code": "storage_error", "message": str(exc)},
        ) from exc
    return {"task_id": task_id, "artifacts": artifacts}


@app.get("/v1/tasks/{task_id}/evaluation")
def get_task_evaluation(task_id: str) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    ev = tasks.get_evaluation(task_id)
    if not ev:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "evaluation not found"},
        )
    return ev


@app.post("/v1/tasks/{task_id}/evaluate")
def evaluate_task(task_id: str, method: str = "heuristic") -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    if row.get("status") not in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "not_terminal",
                "message": f"task status={row.get('status')} is not terminal",
            },
        )
    try:
        return tasks.evaluate(task_id, method=method or "heuristic")
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc


@app.get("/v1/tasks/{task_id}/memory")
def get_task_memory(task_id: str) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    return {"task_id": task_id, "memories": tasks.list_memory(task_id)}


@app.put("/v1/tasks/{task_id}/memory")
def put_task_memory(task_id: str, body: MemoryPutRequest) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        return tasks.put_memory(
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


@app.delete("/v1/tasks/{task_id}/memory/{memory_key}")
def delete_task_memory(task_id: str, memory_key: str) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    ok = tasks.delete_memory(task_id, memory_key)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "memory key not found"},
        )
    return {"deleted": True, "task_id": task_id, "memory_key": memory_key}


@app.get("/v1/memory")
def list_tenant_memory(limit: int = 50) -> dict[str, Any]:
    return {"memories": tasks.list_tenant_memory(limit=limit)}


@app.put("/v1/memory")
def put_tenant_memory(body: TenantMemoryPutRequest) -> dict[str, Any]:
    try:
        return tasks.put_tenant_memory(
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


@app.get("/v1/memory/search")
def search_tenant_memory(q: str, top_k: int = 5) -> dict[str, Any]:
    query = (q or "").strip()
    if not query:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "q is required"},
        )
    return {"query": query, "hits": tasks.search_tenant_memory(query, top_k=top_k)}


@app.delete("/v1/memory/{memory_key}")
def delete_tenant_memory(memory_key: str) -> dict[str, Any]:
    ok = tasks.delete_tenant_memory(memory_key)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "memory key not found"},
        )
    return {"deleted": True, "memory_key": memory_key}


@app.post("/v1/tasks/{task_id}/memory/promote")
def promote_task_memory(task_id: str) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    written = tasks.promote_task_memory(task_id)
    return {"task_id": task_id, "promoted": len(written), "memories": written}


@app.get("/v1/workflows")
def list_workflows(status: str | None = None) -> dict[str, Any]:
    return {"workflows": workflows.list(status=status)}


@app.post("/v1/workflows", status_code=201)
def create_workflow(body: CreateWorkflowRequest) -> dict[str, Any]:
    try:
        return workflows.create(
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


@app.get("/v1/workflows/{workflow_id}")
def get_workflow(workflow_id: str) -> dict[str, Any]:
    row = workflows.get(workflow_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "workflow not found"})
    return row


@app.post("/v1/workflows/{workflow_id}/run", status_code=201)
def run_workflow(workflow_id: str, body: RunWorkflowRequest) -> dict[str, Any]:
    try:
        return tasks.run_workflow(
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
        raise HTTPException(status_code=status, detail={"code": code, "message": msg}) from exc


class InstallRequest(BaseModel):
    package_id: str | None = None
    endpoint: str | None = None


@app.get("/v1/marketplace")
def marketplace_catalog(q: str | None = None) -> dict[str, Any]:
    return {"packages": marketplace.catalog(q=q)}


@app.post("/v1/marketplace/install", status_code=201)
def marketplace_install(body: InstallRequest) -> dict[str, Any]:
    try:
        return marketplace.install(package_id=body.package_id, endpoint=body.endpoint)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "install_failed", "message": str(exc)},
        ) from exc


@app.post("/v1/health/probe")
def health_probe() -> dict[str, Any]:
    results = HealthMonitor().probe_all()
    return {
        "probed": len(results),
        "online": sum(1 for r in results if r.get("healthy")),
        "results": results,
    }


async def _pubsub_listen(websocket: WebSocket, pubsub, *, msg_type: str, task_id: str | None = None):
    """Forward Redis Pub/Sub messages to a WebSocket (non-competing fan-out)."""
    try:
        while True:
            msg = await asyncio.to_thread(
                pubsub.get_message, ignore_subscribe_messages=True, timeout=1.0
            )
            if not msg or msg.get("type") != "message":
                await asyncio.sleep(0)
                continue
            data = msg.get("data")
            if isinstance(data, bytes):
                data = data.decode("utf-8", errors="replace")
            fields: dict[str, Any]
            try:
                import json

                parsed = json.loads(data) if isinstance(data, str) else {}
                fields = parsed if isinstance(parsed, dict) else {"raw": data}
            except Exception:  # noqa: BLE001
                fields = {"raw": str(data)}
            payload = {
                "type": msg_type,
                "event_type": fields.get("event_type"),
                "data": fields,
                "timestamp": time.time(),
            }
            if task_id:
                payload["task_id"] = task_id
            await websocket.send_json(payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("pubsub listen error: %s", exc)


# WebSocket endpoints — Redis Pub/Sub fan-out (Phase 14)
@app.websocket("/v1/tasks/{task_id}/events/ws")
async def websocket_task_events(websocket: WebSocket, task_id: str):
    """Real-time task events via Redis Pub/Sub (each client gets a full copy)."""
    await websocket.accept()
    await websocket_manager.connect(websocket, task_id)
    pubsub = None
    event_listener = None

    try:
        row = tasks.get(task_id)
        if row:
            await websocket.send_json({"type": "initial_state", "task_id": task_id, "data": row})

        events = tasks.events(task_id)
        if events:
            await websocket.send_json({"type": "initial_events", "task_id": task_id, "data": events})

        pubsub = streams.subscribe_task_events(task_id)
        event_listener = asyncio.create_task(
            _pubsub_listen(websocket, pubsub, msg_type="task_event", task_id=task_id)
        )

        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in {"ping", '{"type":"ping"}'}:
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "echo", "message": f"Received: {data}"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("WebSocket error for task %s: %s", task_id, e)
    finally:
        if event_listener:
            event_listener.cancel()
            try:
                await event_listener
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if pubsub is not None:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except Exception:  # noqa: BLE001
                pass
        await websocket_manager.disconnect(websocket, task_id)


@app.websocket("/v1/events/ws")
async def websocket_global_events(websocket: WebSocket):
    """Global system events via Redis Pub/Sub."""
    await websocket.accept()
    await websocket_manager.connect(websocket)
    pubsub = None
    event_listener = None

    try:
        overview = tasks.overview()
        await websocket.send_json({"type": "initial_state", "data": overview})

        pubsub = streams.subscribe_global_events()
        event_listener = asyncio.create_task(
            _pubsub_listen(websocket, pubsub, msg_type="system_event")
        )

        while True:
            data = await websocket.receive_text()
            if data.strip().lower() in {"ping", '{"type":"ping"}'}:
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "echo", "message": f"Received: {data}"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Global WebSocket error: %s", e)
    finally:
        if event_listener:
            event_listener.cancel()
            try:
                await event_listener
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if pubsub is not None:
            try:
                pubsub.unsubscribe()
                pubsub.close()
            except Exception:  # noqa: BLE001
                pass
        await websocket_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    import threading
    import os

    # Get orchestrator port from environment or default to 8090
    orchestrator_port = int(os.getenv("ORCHESTRATOR_PORT", "8090"))
    orchestrator_id = os.getenv("ORCHESTRATOR_ID", "orchestrator-default")

    print(f"Starting Orchestrator {orchestrator_id} on port {orchestrator_port}")

    # Start metrics server in a separate thread (optional; /metrics also on main port)
    def start_metrics():
        try:
            # Prefer METRICS_PORT; never use port+1000 (8090→9090 collides with Prometheus)
            metrics_port = int(os.getenv("METRICS_PORT", "9091"))
            start_metrics_server(port=metrics_port)
            print(f"Metrics server started on port {metrics_port}")
        except Exception as e:
            print(f"Failed to start metrics server: {e}")

    metrics_thread = threading.Thread(target=start_metrics, daemon=True)
    metrics_thread.start()

    uvicorn.run("main:app", host="0.0.0.0", port=orchestrator_port, reload=False)
