"""Orchestrator HTTP API (Tasks + Artifacts + Workflows)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from service import TaskService
from governance import GovernanceService
from workflows import WorkflowService
from marketplace import MarketplaceService
from marketplace.bundle import (
    BundleError,
    attach_bundle_meta,
    build_agent_bundle,
    render_install_ps1,
    render_install_sh,
)
from marketplace.manifest import ManifestValidationError
from health_monitor import HealthMonitor
from observability import start_metrics_server, get_metrics_text
from observability.a2a_metrics import (
    observe_execution_event,
    observe_governance_denial,
    observe_marketplace_event,
)
from websocket import manager as websocket_manager
from streams import StreamClient
from quota import QuotaExceeded
from billing.stripe_checkout import StripeCheckoutError
from billing.webhook import WebhookError
from execution import (
    ExecutionService,
    build_execution_service,
    CapacityQueue,
    cancel_fanout,
    RecoveryScheduler,
    ExecutionConfig,
)
from agent_lifecycle import AgentLifecycleService
from execution.state_machine import IllegalTransition
from scheduling import (
    SchedulingService,
    TenantContext,
    set_tenant_context,
    reset_tenant_context,
    assert_same_tenant,
    DEFAULT_TENANT_ID,
)

# Phase 36.8: Recovery and DR integration
from recovery_and_dr import StartupReconciler

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
# Phase 2.2: OS-level governance authority. Reuses the runtime graph so depth /
# visits are reconstructed from recorded edges (anti-tamper), never trusted from
# the caller. Agents call POST /v1/governance/check before delegating.
governance = GovernanceService(runtime_graph=tasks.runtime_graph)
workflows = WorkflowService()
# Phase 4: Postgres Execution Store by default (EXECUTION_STORE=memory for tests).
_exec_cfg = ExecutionConfig.from_env()
execution = build_execution_service(_exec_cfg)
agent_lifecycle = AgentLifecycleService(event_bus=execution.events)
marketplace = MarketplaceService(event_bus=execution.events, lifecycle=agent_lifecycle)
streams = StreamClient()
execution.events.on_emit(
    lambda ev: observe_marketplace_event(ev.event_type, ev.payload or {})
)
capacity_queue = CapacityQueue(max_depth=_exec_cfg.max_queue_depth)
recovery_scheduler: RecoveryScheduler | None = None
# Phase 5: Intelligent Scheduling façade (Router stays discovery; Scheduler selects)
scheduling = SchedulingService()
execution.cost_service = scheduling.cost  # type: ignore[attr-defined]
execution.events.on_emit(
    lambda ev: observe_execution_event(ev.event_type, {**(ev.payload or {}), "duration_ms": (ev.payload or {}).get("duration_ms")})
)

# P4.15: Router filters by lifecycle + queue depth
try:
    tasks.router.set_lifecycle_hooks(
        lifecycle_checker=agent_lifecycle.router_accepts,
        capacity_queue_depth=capacity_queue.depth,
    )
except Exception as exc:  # noqa: BLE001
    logger.warning("router lifecycle hooks not attached: %s", exc)

# Phase 36.8: Initialize startup reconciler
startup_reconciler = StartupReconciler()

# Instrument FastAPI for tracing
if TRACING_AVAILABLE:
    instrument_fastapi(app)


@app.on_event("startup")
async def startup_event():
    """Startup: Phase 36.8 reconciliation + Phase 4 RecoveryScheduler."""
    global recovery_scheduler
    logger.info("Running startup reconciliation...")

    try:
        issues = startup_reconciler.run_full_reconciliation()

        if issues:
            logger.warning(f"Found {len(issues)} consistency issues during startup:")
            for issue in issues:
                logger.warning(f"  - {issue.issue_type.value}: {issue.description} (severity: {issue.severity})")

            # Auto-fix critical issues
            fixed = startup_reconciler.auto_fix_critical_issues()
            logger.info(f"Auto-fixed {sum(fixed.values())} critical issues: {fixed}")
        else:
            logger.info("No consistency issues found during startup")

    except Exception as e:
        logger.error(f"Startup reconciliation failed: {e}")
        # Don't fail startup if reconciliation fails

    if _exec_cfg.recovery_enabled:
        recovery_scheduler = RecoveryScheduler(
            execution,
            interval_s=_exec_cfg.recovery_interval_s,
            batch_size=_exec_cfg.recovery_batch_size,
            lease_seconds=_exec_cfg.lease_duration_s,
            owner_id=_exec_cfg.owner_id or "orchestrator-recovery",
            agent_lifecycle=agent_lifecycle,
        )
        recovery_scheduler.start()
        logger.info("Phase 4 RecoveryScheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    """P4.20: stop recovery loop; leases expire for peer takeover."""
    global recovery_scheduler
    if recovery_scheduler is not None:
        recovery_scheduler.stop()
        recovery_scheduler = None
        logger.info("Phase 4 RecoveryScheduler stopped (leases retained for takeover)")

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
    """HITL decision — LangGraph-style resume with optional human content.

    ``input`` is injected into the approved node's ``output_json.hitl`` and
    surfaces in downstream ``_compose_query`` as human guidance.
    """

    node_key: str | None = None
    reason: str = "rejected by user"
    input: str | None = None



class MemoryPutRequest(BaseModel):
    memory_key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantMemoryPutRequest(BaseModel):
    memory_key: str
    content: str
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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


class GovernanceCheckRequest(BaseModel):
    """An Agent's proposed delegation, submitted to the OS for an authoritative
    governance decision. Depth / visits are NOT trusted from the caller: the OS
    reconstructs them from its own runtime graph."""

    root_task_id: str
    caller_agent_id: str
    target_agent_id: str
    caller_task_id: str | None = None
    correlation_id: str | None = None
    tenant_id: str | None = None
    requested_units: float | None = None
    units_estimated: bool = True
    deadline: str | None = None
    claimed_depth: int | None = None


class GovernanceReleaseRequest(BaseModel):
    """Release in-flight concurrency reserved by a prior successful check."""

    context: dict[str, Any] = Field(default_factory=dict)


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


def _io_spec(spec: IOModeSpec | None) -> dict[str, Any]:
    if spec is None:
        return {}
    out: dict[str, Any] = {}
    if spec.type:
        out["type"] = spec.type
    if spec.modes:
        out["modes"] = spec.modes
    return out


@app.post("/v1/discover")
def discover_agents(body: DiscoverRequest) -> dict[str, Any]:
    """A2A OS: capability-aware Agent discovery, open to any Agent.

    Returns ranked candidate Agents; the caller decides whom to invoke. This is
    infrastructure, not central orchestration.
    """
    try:
        return tasks.discover(
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


@app.post("/v1/route")
def route_request(body: RouteRequest) -> dict[str, Any]:
    """A2A OS: select the best Agent for a request, open to any Agent."""
    try:
        return tasks.route(
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


@app.get("/v1/evaluations")
def list_evaluations(
    limit: int = 50,
    min_score: float | None = None,
) -> dict[str, Any]:
    return {
        "evaluations": tasks.list_evaluations(limit=limit, min_score=min_score),
    }


@app.post("/v1/runtime/edges", status_code=201)
def record_runtime_edge(body: RuntimeEdgeRequest) -> dict[str, Any]:
    """A2A OS: record an Agent-to-Agent call edge in the runtime execution graph.

    Called by Agents (best-effort) after they delegate to a peer, so the OS can
    reconstruct the full call graph without forcing calls through a central
    orchestrator.
    """
    if not body.caller_agent_id or not body.target_agent_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "caller_agent_id and target_agent_id required"},
        )
    try:
        return tasks.record_runtime_edge(
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


@app.get("/v1/runtime/graph/{root_task_id}")
def runtime_graph(root_task_id: str) -> dict[str, Any]:
    """A2A OS: reconstruct the runtime execution graph for a root task."""
    try:
        return tasks.runtime_graph_view(root_task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_graph_error", "message": str(exc)},
        ) from exc


@app.get("/v1/collaboration/graph/{root_task_id}")
def collaboration_graph(root_task_id: str, request: Request) -> dict[str, Any]:
    """A2A OS: frontend-ready collaboration graph (nodes + links + tree)."""
    _forbid_cross_tenant(request, _resource_tenant_from_graph(root_task_id))
    try:
        graph = tasks.collaboration_graph_view(root_task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "runtime_graph_error", "message": str(exc)},
        ) from exc
    for node in graph.get("nodes") or []:
        if node.get("type") == "agent":
            life = agent_lifecycle.get(node["id"])
            if life:
                node["state"] = life.get("state")
                node["active_tasks"] = life.get("active_tasks")
                node["last_seen"] = life.get("last_seen")
                node["task_count"] = life.get("active_tasks")
    return graph


@app.get("/v1/collaboration/events/{root_task_id}")
def collaboration_events(root_task_id: str, request: Request) -> dict[str, Any]:
    """Phase 3: ordered execution events for a collaboration root."""
    _forbid_cross_tenant(request, _resource_tenant_from_graph(root_task_id))
    items = execution.events.list_for_root(root_task_id)
    # Filter events that carry a mismatched tenant_id in payload when present
    ctx = _tenant_from_request(request)
    if ctx.tenant_id != DEFAULT_TENANT_ID:
        items = [
            e
            for e in items
            if not (e.get("payload") or {}).get("tenant_id")
            or str((e.get("payload") or {}).get("tenant_id")) == ctx.tenant_id
        ]
    return {"root_task_id": root_task_id, "events": items, "count": len(items)}


@app.websocket("/v1/collaboration/stream/{root_task_id}")
async def collaboration_stream(websocket: WebSocket, root_task_id: str):
    """P4.16: realtime collaboration events ordered by per-root sequence."""
    await websocket.accept()
    # Snapshot existing events first
    try:
        snapshot = execution.events.list_for_root(root_task_id)
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

    queue: asyncio.Queue = asyncio.Queue(maxsize=256)

    def _hook(ev):
        if ev.root_task_id != root_task_id:
            return
        try:
            queue.put_nowait(ev.to_dict())
        except asyncio.QueueFull:
            pass

    execution.events.on_emit(_hook)
    try:
        while True:
            try:
                # Multiplex: client pings + new events
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
                    payload = event_task.result()
                    await websocket.send_json(
                        {
                            "type": "event",
                            "root_task_id": root_task_id,
                            "sequence": (payload.get("payload") or {}).get("sequence"),
                            "event": payload,
                        }
                    )
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
            if _hook in execution.events._hooks:
                execution.events._hooks.remove(_hook)
        except Exception:  # noqa: BLE001
            pass


@app.post("/v1/governance/check")
def governance_check(body: GovernanceCheckRequest) -> dict[str, Any]:
    """A2A OS: authoritative governance decision for a proposed Agent delegation.

    Agents call this *before* delegating. The OS decides — Agents cannot raise
    their own limits. Depth and per-Agent visit counts are reconstructed from the
    recorded runtime graph, so a caller cannot under-report lineage to bypass a
    limit. Counters (calls, budget) are DB-atomic and concurrency is Redis-atomic,
    so they hold across the multiple processes of a real Agent network.
    """
    if not body.caller_agent_id or not body.target_agent_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error",
                    "message": "caller_agent_id and target_agent_id required"},
        )
    try:
        decision = governance.check_and_reserve(
            root_task_id=body.root_task_id,
            caller_agent_id=body.caller_agent_id,
            target_agent_id=body.target_agent_id,
            caller_task_id=body.caller_task_id,
            correlation_id=body.correlation_id,
            tenant_id=body.tenant_id,
            requested_units=body.requested_units,
            units_estimated=body.units_estimated,
            deadline=body.deadline,
            claimed_depth=body.claimed_depth,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "governance_error", "message": str(exc)},
        ) from exc
    result = decision.to_dict()
    if not result.get("allowed"):
        observe_governance_denial(result.get("code") or "UNKNOWN")
        return result
    # Phase 3/4: capacity / drain gate (legacy untracked agents still allowed).
    ok, reason = agent_lifecycle.accepts_delegation(body.target_agent_id)
    if ok:
        return result
    if reason == "at_capacity" and _exec_cfg.queue_enabled:
        # P4.13–14: WAIT instead of hard reject when capacity_overflow allows
        overflow = "wait"
        try:
            from execution.policy import PolicyEngine

            pol = PolicyEngine().resolve()
            overflow = pol.capacity_overflow or "wait"
        except Exception:  # noqa: BLE001
            pass
        if overflow == "wait":
            q = capacity_queue.enqueue(
                task_id=body.caller_task_id or body.root_task_id,
                agent_id=body.target_agent_id,
                root_task_id=body.root_task_id,
                correlation_id=body.correlation_id,
            )
            if q.get("queued"):
                # Mark execution WAITING when a record exists
                tid = body.caller_task_id or body.root_task_id
                try:
                    if execution.get(tid) is None:
                        execution.create(
                            task_id=tid,
                            root_task_id=body.root_task_id,
                            correlation_id=body.correlation_id or tid,
                            agent_id=body.target_agent_id,
                            metadata={"queued": True},
                        )
                    execution.transition(tid, "WAITING")
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "allowed": True,
                    "code": "QUEUED",
                    "reason": "capacity wait queue",
                    "queued": True,
                    "queue": q,
                    "context": decision.to_dict().get("context")
                    if hasattr(decision, "to_dict")
                    else result.get("context"),
                }
            observe_governance_denial("CAPACITY_QUEUE_FULL")
            return {
                "allowed": False,
                "code": "CONCURRENCY_LIMIT_EXCEEDED",
                "reason": "max_queue_depth exceeded",
                "queue": q,
                "context": {"root_task_id": body.root_task_id},
            }
    observe_governance_denial("CAPACITY" if reason == "at_capacity" else "LIFECYCLE")
    return {
        "allowed": False,
        "code": "CONCURRENCY_LIMIT_EXCEEDED" if reason == "at_capacity" else "POLICY_DISABLED",
        "reason": f"agent lifecycle rejected: {reason}",
        "context": {"root_task_id": body.root_task_id, "lifecycle_reason": reason},
    }


@app.post("/v1/governance/release")
def governance_release(body: GovernanceReleaseRequest) -> dict[str, Any]:
    """A2A OS: release in-flight concurrency reserved by a prior check."""
    try:
        governance.release(body.context)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "governance_error", "message": str(exc)},
        ) from exc
    return {"released": True}


@app.get("/v1/governance/denials")
def governance_denials(
    root_task_id: str | None = None,
    code: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """A2A OS: audit trail of governance denials (queryable from Task/Audit)."""
    try:
        items = governance.list_denials(root_task_id=root_task_id, code=code, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "governance_error", "message": str(exc)},
        ) from exc
    return {"denials": items, "count": len(items)}


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
def get_task(task_id: str, include_graph: bool = False) -> dict[str, Any]:
    if include_graph:
        row = tasks.get_with_graph(task_id)
    else:
        row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    # Phase 3: attach execution snapshot when available (non-breaking).
    try:
        row = dict(row)
        row["execution"] = execution.get_execution_view(task_id)
    except Exception:  # noqa: BLE001
        pass
    return row


@app.get("/v1/tasks/{task_id}/execution")
def get_task_execution(task_id: str, request: Request) -> dict[str, Any]:
    """Phase 3: Execution Record view (source of truth)."""
    _forbid_cross_tenant(request, _resource_tenant_from_execution(task_id))
    view = execution.get_execution_view(task_id)
    if not view.get("execute") and not view.get("delegate"):
        # Still return empty scaffold so clients can poll after create
        row = tasks.get(task_id)
        if not row:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    return view


# ── Phase 5: Scheduling / Cost / Tenant APIs ───────────────────────────────

class SchedulingRequest(BaseModel):
    agents: list[dict[str, Any]] = Field(default_factory=list)
    requirement: dict[str, Any] = Field(default_factory=dict)
    exclude_agent_ids: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.1
    skill: str | None = None


def _tenant_from_request(request: Request) -> TenantContext:
    return TenantContext.from_headers(dict(request.headers))


def _forbid_cross_tenant(request: Request, resource_tenant_id: str | None) -> None:
    """P5.12: non-default tenants cannot read other tenants' data."""
    ctx = _tenant_from_request(request)
    try:
        assert_same_tenant(resource_tenant_id or DEFAULT_TENANT_ID, ctx=ctx)
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "tenant_forbidden", "message": str(exc)},
        ) from exc


def _resource_tenant_from_execution(task_id: str) -> str | None:
    view = execution.get_execution_view(task_id)
    for key in ("execute", "delegate"):
        row = view.get(key) or {}
        if row.get("tenant_id"):
            return str(row["tenant_id"])
    return None


def _resource_tenant_from_graph(root_task_id: str) -> str | None:
    try:
        edges = tasks.runtime_graph.list_edges(root_task_id)
        for e in edges or []:
            if e.get("tenant_id"):
                return str(e["tenant_id"])
    except Exception:  # noqa: BLE001
        pass
    return None


def _agents_for_scheduling(body_agents: list[dict[str, Any]], skill: str | None) -> list[dict[str, Any]]:
    if body_agents:
        return body_agents
    # Fall back to router discover when callers omit agent list
    try:
        if skill:
            ranked = tasks.router.rank(skill)
            return [
                {
                    "agent_id": a.agent_id,
                    "agent_key": a.agent_key,
                    "name": a.name,
                    "endpoint": a.endpoint,
                    "status": a.status,
                    "skills": list(a.skills or []),
                    "priority": a.priority,
                    "latency_ms": (a.score_breakdown or {}).get("latency_ms"),
                }
                for a in ranked
            ]
    except Exception:  # noqa: BLE001
        pass
    return []


@app.get("/v1/scheduling/candidates")
def scheduling_candidates(
    request: Request,
    skill: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Phase 5: capability-filtered candidates (uses Router discover + Scheduler filter)."""
    ctx = _tenant_from_request(request)
    token = set_tenant_context(ctx)
    try:
        agents = _agents_for_scheduling([], skill or None)
        return scheduling.candidates(
            agents[:limit],
            requirement={"skill": skill} if skill else {},
            ctx=ctx,
        )
    finally:
        reset_tenant_context(token)


@app.post("/v1/scheduling/preview")
def scheduling_preview(body: SchedulingRequest, request: Request) -> dict[str, Any]:
    ctx = _tenant_from_request(request)
    token = set_tenant_context(ctx)
    try:
        skill = body.skill or (body.requirement or {}).get("skill")
        agents = _agents_for_scheduling(body.agents, skill)
        req = dict(body.requirement or {})
        if skill and not req.get("skill"):
            req["skill"] = skill
        return scheduling.preview(
            agents,
            requirement=req,
            exclude_agent_ids=body.exclude_agent_ids,
            estimated_cost=body.estimated_cost,
            ctx=ctx,
        )
    finally:
        reset_tenant_context(token)


@app.post("/v1/scheduling/select")
def scheduling_select(body: SchedulingRequest, request: Request) -> dict[str, Any]:
    ctx = _tenant_from_request(request)
    token = set_tenant_context(ctx)
    try:
        skill = body.skill or (body.requirement or {}).get("skill")
        agents = _agents_for_scheduling(body.agents, skill)
        req = dict(body.requirement or {})
        if skill and not req.get("skill"):
            req["skill"] = skill
        return scheduling.select(
            agents,
            requirement=req,
            exclude_agent_ids=body.exclude_agent_ids,
            estimated_cost=body.estimated_cost,
            ctx=ctx,
            commit_budget=True,
        )
    finally:
        reset_tenant_context(token)


@app.post("/v1/scheduling/simulate")
def scheduling_simulate(body: dict[str, Any]) -> dict[str, Any]:
    """Phase 5.13: offline simulator (no execution side effects)."""
    return scheduling.simulate(body)


@app.get("/v1/agents/{agent_id}/capacity")
def agent_capacity(agent_id: str) -> dict[str, Any]:
    health = agent_lifecycle.health(agent_id)
    depth = capacity_queue.depth(agent_id)
    quota = scheduling.resources.get_quota()
    ok, reason = scheduling.resources.check_agent_capacity(
        health, queue_depth=depth, quota=quota
    )
    return {
        "agent_id": agent_id,
        "health": health,
        "queue_depth": depth,
        "quota": quota.to_dict(),
        "accepts": ok,
        "reason": reason,
    }


@app.get("/v1/agents/{agent_id}/reliability")
def agent_reliability(agent_id: str) -> dict[str, Any]:
    # Refresh from in-memory execution store when available
    try:
        if hasattr(execution.store, "_by_key"):
            records = list(execution.store._by_key.values())  # type: ignore[attr-defined]
            scheduling.reliability.compute_from_records(
                [r for r in records if r.agent_id == agent_id]
            )
    except Exception:  # noqa: BLE001
        pass
    rel = scheduling.reliability.get(agent_id)
    return rel.to_dict() if rel else {
        "agent_id": agent_id,
        "sample_size": 0,
        "availability": 1.0,
        "success_rate": 0.0,
        "note": "insufficient_samples",
    }


@app.get("/v1/tasks/{task_id}/cost")
def task_cost(task_id: str, request: Request) -> dict[str, Any]:
    cost = scheduling.cost.task_cost(task_id)
    items = cost.get("items") or []
    resource_tenant = None
    for it in items:
        if it.get("tenant_id"):
            resource_tenant = str(it["tenant_id"])
            break
    if resource_tenant is None:
        resource_tenant = _resource_tenant_from_execution(task_id)
    _forbid_cross_tenant(request, resource_tenant)
    return cost


@app.get("/v1/tasks/{task_id}/cost/breakdown")
def task_cost_breakdown(task_id: str, request: Request) -> dict[str, Any]:
    breakdown = scheduling.cost.task_breakdown(task_id)
    items = breakdown.get("items") or []
    resource_tenant = None
    for it in items:
        if it.get("tenant_id"):
            resource_tenant = str(it["tenant_id"])
            break
    if resource_tenant is None:
        resource_tenant = _resource_tenant_from_execution(task_id)
    _forbid_cross_tenant(request, resource_tenant)
    return breakdown


@app.get("/v1/tenants/{tenant_id}/quota")
def tenant_quota(tenant_id: str, request: Request) -> dict[str, Any]:
    _forbid_cross_tenant(request, tenant_id)
    q = scheduling.resources.get_quota(tenant_id=tenant_id)
    return q.to_dict()


@app.get("/v1/tenants/{tenant_id}/budget")
def tenant_budget(tenant_id: str, request: Request) -> dict[str, Any]:
    _forbid_cross_tenant(request, tenant_id)
    budgets = scheduling.budget.ensure_tenant_budget(tenant_id)
    return {k: v.to_dict() for k, v in budgets.items()}


@app.get("/v1/tenants/{tenant_id}/cost")
def tenant_cost(tenant_id: str, request: Request) -> dict[str, Any]:
    _forbid_cross_tenant(request, tenant_id)
    return scheduling.cost.tenant_cost(tenant_id)


class TenantPolicyBody(BaseModel):
    policy: dict[str, Any] = Field(default_factory=dict)


@app.get("/v1/tenants/{tenant_id}/policy")
def get_tenant_policy(tenant_id: str, request: Request) -> dict[str, Any]:
    _forbid_cross_tenant(request, tenant_id)
    return {"tenant_id": tenant_id, "policy": scheduling.policies.get_tenant_policy(tenant_id).to_dict()}


@app.post("/v1/tenants/{tenant_id}/policy")
def set_tenant_policy(tenant_id: str, body: TenantPolicyBody, request: Request) -> dict[str, Any]:
    _forbid_cross_tenant(request, tenant_id)
    doc = scheduling.policies.set_tenant_policy(tenant_id, body.policy)
    return {"tenant_id": tenant_id, "policy": doc.to_dict()}


@app.post("/v1/scheduling/recovery-plan")
def scheduling_recovery_plan(body: dict[str, Any]) -> dict[str, Any]:
    """Phase 5.8: classify failure → retry / reselect / abort."""
    return scheduling.recovery_plan(
        error_code=body.get("error_code"),
        error=body.get("error"),
        agent_id=body.get("agent_id"),
        agent_state=body.get("agent_state"),
        exclude_agent_ids=body.get("exclude_agent_ids"),
    )

@app.post("/v1/tasks/{task_id}/recover")
def recover_task(task_id: str) -> dict[str, Any]:
    """Phase 3: recover a stale/failed/timeout execution."""
    # Ensure a record exists for orchestrator-created tasks
    if execution.get(task_id) is None:
        row = tasks.get(task_id)
        if not row:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
        execution.create(
            task_id=task_id,
            root_task_id=task_id,
            correlation_id=task_id,
            metadata={"seeded_from": "recover"},
        )
        execution.transition(task_id, "TIMEOUT")  # mark uncertain so recover can retry
    try:
        return execution.recover(task_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400,
            detail={"code": "recover_error", "message": str(exc)},
        ) from exc


class NodeReplayRequest(BaseModel):
    clear_downstream: bool = True


@app.get("/v1/tasks/{task_id}/checkpoints")
def list_task_checkpoints(
    task_id: str,
    node_key: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """List node-level checkpoints for time-travel / replay UI."""
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        items = tasks.list_checkpoints(task_id, node_key=node_key, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail={"code": "checkpoint_error", "message": str(exc)},
        ) from exc
    return {"task_id": task_id, "checkpoints": items, "count": len(items)}


@app.post("/v1/tasks/{task_id}/nodes/{node_key}/replay")
def replay_task_node(
    task_id: str,
    node_key: str,
    body: NodeReplayRequest | None = None,
) -> dict[str, Any]:
    """Replay a plan node from its latest checkpoint (retry_same)."""
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        return tasks.replay_from_node(
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


@app.get("/v1/tasks/{task_id}/collaboration-graph")
def task_collaboration_graph(task_id: str) -> dict[str, Any]:
    """A2A OS: collaboration graph rooted at a central Task id.

    Associates the orchestrator's Task with the runtime Agent-to-Agent edges
    recorded under the same ``root_task_id`` (seeded by the executor).
    """
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        graph = tasks.collaboration_graph_view(task_id)
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
    # Phase 3: enrich agent nodes with lifecycle
    for node in graph.get("nodes") or []:
        if node.get("type") == "agent":
            life = agent_lifecycle.get(node["id"])
            if life:
                node["state"] = life.get("state")
                node["active_tasks"] = life.get("active_tasks")
                node["last_seen"] = life.get("last_seen")
    return graph


@app.post("/v1/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict[str, Any]:
    # Resolve A2A cancel targets before OS marks nodes cancelled (status flips).
    agent_endpoints: dict[str, str] = {}
    try:
        if hasattr(marketplace, "list_agents"):
            for a in marketplace.list_agents() or []:
                aid = a.get("agent_id") or a.get("id")
                ep = a.get("endpoint") or a.get("url")
                if aid and ep:
                    agent_endpoints[str(aid)] = str(ep)
    except Exception:  # noqa: BLE001
        pass

    extra_a2a_targets: list[dict[str, str]] = []
    try:
        sched = getattr(tasks, "scheduler", None)
        if sched is not None and hasattr(sched, "list_a2a_cancel_targets"):
            for item in sched.list_a2a_cancel_targets(task_id) or []:
                aid = item.get("agent_id")
                ep = agent_endpoints.get(str(aid)) if aid else None
                if not ep:
                    continue
                # OS task id is rootTaskId/correlationId on harness agents.
                extra_a2a_targets.append(
                    {"endpoint": ep, "task_id": task_id, "agent_id": str(aid)}
                )
                a2a_id = item.get("a2a_task_id")
                if a2a_id and str(a2a_id) != task_id:
                    extra_a2a_targets.append(
                        {"endpoint": ep, "task_id": str(a2a_id), "agent_id": str(aid)}
                    )
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_a2a_cancel_targets skipped: %s", exc)

    row = tasks.cancel(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})

    def _a2a_cancel(endpoint: str, child_task_id: str) -> bool:
        try:
            from a2a_sdk import A2AClient

            client = A2AClient(endpoint)
            return bool(client.cancel_task(child_task_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("A2A cancel failed endpoint=%s task=%s: %s", endpoint, child_task_id, exc)
            return False

    cascade = cancel_fanout(
        root_task_id=task_id,
        execution_service=execution,
        runtime_graph=tasks.runtime_graph,
        a2a_cancel=_a2a_cancel if (agent_endpoints or extra_a2a_targets) else None,
        agent_endpoints=agent_endpoints or None,
        extra_a2a_targets=extra_a2a_targets or None,
    )
    capacity_queue.cancel(task_id)
    out = dict(row)
    out["execution_cancel"] = cascade
    return out


class AgentHeartbeatRequest(BaseModel):
    active_tasks: int | None = None
    load: float | None = None
    version: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


@app.get("/v1/agents/{agent_id}/health")
@app.get("/v1/agent-runtime/{agent_id}/health")
def agent_health(agent_id: str) -> dict[str, Any]:
    """Phase 3: OS-side agent health + lifecycle."""
    return agent_lifecycle.health(agent_id)


@app.post("/v1/agents/{agent_id}/heartbeat")
@app.post("/v1/agent-runtime/{agent_id}/heartbeat")
def agent_heartbeat(agent_id: str, body: AgentHeartbeatRequest | None = None) -> dict[str, Any]:
    body = body or AgentHeartbeatRequest()
    rec = agent_lifecycle.heartbeat(
        agent_id,
        active_tasks=body.active_tasks,
        load=body.load,
        version=body.version,
        capabilities=body.capabilities or None,
    )
    return rec.to_dict()


@app.post("/v1/agents/{agent_id}/drain")
@app.post("/v1/agent-runtime/{agent_id}/drain")
def agent_drain(agent_id: str) -> dict[str, Any]:
    """Phase 3: stop accepting new work; finish in-flight then OFFLINE."""
    try:
        if agent_lifecycle.get(agent_id) is None:
            agent_lifecycle.register(agent_id)
            agent_lifecycle.mark_ready(agent_id)
        rec = agent_lifecycle.drain(agent_id)
    except (KeyError, IllegalTransition) as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "lifecycle_error", "message": str(exc)},
        ) from exc
    return rec.to_dict()


@app.post("/v1/tasks/{task_id}/approve")
def approve_task(task_id: str, body: HitlDecisionRequest | None = None) -> dict[str, Any]:
    row = tasks.get(task_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "task not found"})
    try:
        return tasks.approve(
            task_id,
            node_key=(body.node_key if body else None),
            human_input=(body.input if body else None),
        )
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
    version: str | None = None
    sandbox: str = "local_process"


class ManifestRegisterRequest(BaseModel):
    manifest: dict[str, Any] | None = None
    name: str | None = None
    version: str | None = None
    description: str | None = None
    author: str | None = None
    runtime: dict[str, Any] | None = None
    endpoint: str | None = None
    protocol: str | None = "a2a"
    capabilities: list[str] | None = None
    skills: list[str] | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    requirements: dict[str, Any] | None = None
    permissions: list[str] | dict[str, Any] | None = None
    dependencies: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    activate: bool = True
    skip_gateway: bool = False

    def as_manifest_dict(self) -> dict[str, Any]:
        if self.manifest:
            return dict(self.manifest)
        data = self.model_dump(exclude_none=True)
        data.pop("activate", None)
        data.pop("skip_gateway", None)
        data.pop("manifest", None)
        return data


class SkillSearchRequest(BaseModel):
    skill: str | None = None
    name: str | None = None
    q: str | None = None
    capability: str | None = None
    input: str | None = None
    output: str | None = None
    modality: str | None = None
    resource: str | None = None
    version: str | None = None
    tenant: str | None = None
    tags: list[str] | None = None


class SkillRegisterRequest(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str = ""
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    requirements: dict[str, Any] | None = None
    dependencies: dict[str, Any] | None = None
    tags: list[str] | None = None


class MarketplacePublishRequest(BaseModel):
    manifest: dict[str, Any]
    package_id: str | None = None
    status: str = "PUBLISHED"


class DiscoverSkillRequest(BaseModel):
    skill: str
    version: str | None = None
    version_constraint: str | None = None


def _public_base_url(request: Request) -> str:
    """Prefer reverse-proxy headers so install one-liners point at the reachable host."""
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "http").split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    if not host:
        return str(request.base_url).rstrip("/")
    return f"{proto}://{host}".rstrip("/")


@app.get("/v1/marketplace")
def marketplace_catalog(request: Request, q: str | None = None) -> dict[str, Any]:
    base = _public_base_url(request)
    pkgs = [
        attach_bundle_meta(p, base_url=base, catalog=marketplace.catalog())
        for p in marketplace.catalog(q=q)
    ]
    return {"packages": pkgs}


@app.get("/v1/marketplace/agents")
def marketplace_agents(request: Request, q: str | None = None) -> dict[str, Any]:
    base = _public_base_url(request)
    pkgs = [
        attach_bundle_meta(p, base_url=base, catalog=marketplace.catalog())
        for p in marketplace.catalog(q=q)
    ]
    return {"packages": pkgs}


@app.post("/v1/marketplace/agents", status_code=201)
def marketplace_publish_agent(body: MarketplacePublishRequest) -> dict[str, Any]:
    try:
        data = dict(body.manifest)
        if body.package_id:
            data["package_id"] = body.package_id
        return marketplace.publish(data, status=body.status)
    except ManifestValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "manifest_invalid", "message": str(exc)}) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail={"code": "publish_failed", "message": str(exc)}) from exc


@app.get("/v1/marketplace/agents/{package_id}")
def marketplace_agent_get(package_id: str, request: Request) -> dict[str, Any]:
    pkg = marketplace.get_package(package_id)
    if not pkg:
        # Allow lookup by agent_key / profile (e.g. claude-coder)
        for item in marketplace.catalog():
            if item.get("agent_key") == package_id or item.get("package_id") == package_id:
                pkg = marketplace.get_package(str(item["package_id"])) or item
                break
    if not pkg:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": package_id})
    return attach_bundle_meta(pkg, base_url=_public_base_url(request), catalog=marketplace.catalog())


def _marketplace_packages_map() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in marketplace.catalog():
        pid = p.get("package_id")
        if pid:
            out[str(pid)] = p
    return out


@app.get("/v1/marketplace/agents/{package_id}/download")
def marketplace_agent_download(package_id: str) -> Response:
    """Download standalone zip: profile + vendored runtime (remote-host deploy)."""
    try:
        data, meta = build_agent_bundle(
            package_id,
            catalog=marketplace.catalog(),
            packages=_marketplace_packages_map(),
        )
    except BundleError as exc:
        raise HTTPException(status_code=404, detail={"code": "bundle_error", "message": str(exc)}) from exc
    filename = meta.get("filename") or f"{package_id}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AOP-Package-Id": str(meta.get("package_id") or package_id),
            "X-AOP-Profile": str(meta.get("profile") or ""),
            "X-AOP-Harness": str(meta.get("harness") or ""),
        },
    )


@app.get("/v1/marketplace/agents/{package_id}/install.ps1")
def marketplace_agent_install_ps1(package_id: str, request: Request) -> Response:
    """Claude Code–style Windows installer: ``irm <url>/install.ps1 | iex``."""
    try:
        script, meta = render_install_ps1(
            package_id,
            base_url=_public_base_url(request),
            catalog=marketplace.catalog(),
            packages=_marketplace_packages_map(),
        )
    except BundleError as exc:
        raise HTTPException(status_code=404, detail={"code": "bundle_error", "message": str(exc)}) from exc
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{meta["profile"]}-install.ps1"',
            "X-AOP-Install": "windows",
        },
    )


@app.get("/v1/marketplace/agents/{package_id}/install.sh")
def marketplace_agent_install_sh(package_id: str, request: Request) -> Response:
    """Unix one-liner: ``curl -fsSL <url>/install.sh | bash``."""
    try:
        script, meta = render_install_sh(
            package_id,
            base_url=_public_base_url(request),
            catalog=marketplace.catalog(),
            packages=_marketplace_packages_map(),
        )
    except BundleError as exc:
        raise HTTPException(status_code=404, detail={"code": "bundle_error", "message": str(exc)}) from exc
    return Response(
        content=script,
        media_type="text/x-shellscript; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{meta["profile"]}-install.sh"',
            "X-AOP-Install": "unix",
        },
    )


# Short aliases (Claude-like): /install/claude-coder.ps1
@app.get("/install/{name}")
def install_alias(name: str, request: Request) -> Response:
    lower = name.lower()
    if lower.endswith(".ps1"):
        return marketplace_agent_install_ps1(name[: -len(".ps1")], request)
    if lower.endswith(".sh"):
        return marketplace_agent_install_sh(name[: -len(".sh")], request)
    raise HTTPException(
        status_code=404,
        detail={
            "code": "not_found",
            "message": f"use /install/<profile>.ps1 or .sh (got {name!r})",
        },
    )


@app.post("/v1/marketplace/agents/{package_id}/publish")
def marketplace_agent_publish(package_id: str) -> dict[str, Any]:
    try:
        return marketplace.publish_status(package_id, "PUBLISHED")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc


@app.post("/v1/marketplace/agents/{package_id}/install", status_code=201)
def marketplace_agent_install(package_id: str, body: InstallRequest | None = None) -> dict[str, Any]:
    body = body or InstallRequest()
    try:
        return marketplace.install(
            package_id=package_id,
            endpoint=body.endpoint,
            version=body.version,
            sandbox=body.sandbox,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "validation_error", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail={"code": "install_failed", "message": str(exc)}) from exc


@app.post("/v1/marketplace/agents/{package_id}/activate")
def marketplace_agent_activate(package_id: str) -> dict[str, Any]:
    try:
        return marketplace.activate(package_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc


@app.post("/v1/marketplace/agents/{package_id}/deactivate")
def marketplace_agent_deactivate(package_id: str) -> dict[str, Any]:
    try:
        return marketplace.deactivate(package_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": str(exc)}) from exc


@app.post("/v1/marketplace/install", status_code=201)
def marketplace_install(body: InstallRequest) -> dict[str, Any]:
    try:
        return marketplace.install(
            package_id=body.package_id,
            endpoint=body.endpoint,
            version=body.version,
            sandbox=body.sandbox,
        )
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


@app.post("/v1/agents/register", status_code=201)
def agents_register_manifest(body: ManifestRegisterRequest) -> dict[str, Any]:
    try:
        return marketplace.register_manifest(
            body.as_manifest_dict(),
            activate=body.activate,
            skip_gateway=body.skip_gateway,
        )
    except ManifestValidationError as exc:
        raise HTTPException(status_code=400, detail={"code": "manifest_invalid", "message": str(exc)}) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail={"code": "permission_denied", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "validation_error", "message": str(exc)}) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail={"code": "register_failed", "message": str(exc)}) from exc


# Gateway owns /v1/agents/* registry — expose manifest register via marketplace + agent-runtime proxies.
@app.post("/v1/marketplace/register", status_code=201)
def marketplace_register_manifest(body: ManifestRegisterRequest) -> dict[str, Any]:
    return agents_register_manifest(body)


@app.post("/v1/agent-runtime/register", status_code=201)
def agent_runtime_register_manifest(body: ManifestRegisterRequest) -> dict[str, Any]:
    return agents_register_manifest(body)


@app.post("/v1/agents/{agent_id}/heartbeat")
def agents_heartbeat(agent_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    return marketplace.heartbeat(
        agent_id,
        active_tasks=body.get("active_tasks"),
        load=body.get("load"),
        version=body.get("version"),
        capabilities=body.get("capabilities"),
    )


@app.post("/v1/agents/{agent_id}/unregister")
def agents_unregister(agent_id: str, agent_key: str | None = None) -> dict[str, Any]:
    return marketplace.unregister(agent_id, agent_key=agent_key)


@app.get("/v1/skills")
def skills_list() -> dict[str, Any]:
    return {"skills": marketplace.list_skills()}


@app.get("/v1/skills/{name}")
def skills_get(name: str) -> dict[str, Any]:
    skill = marketplace.get_skill(name)
    if not skill:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": name})
    return skill


@app.post("/v1/skills", status_code=201)
def skills_register(body: SkillRegisterRequest) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    return marketplace.register_skill(data)


@app.post("/v1/skills/search")
def skills_search(body: SkillSearchRequest) -> dict[str, Any]:
    results = marketplace.search_skills(body.model_dump(exclude_none=True))
    return {"skills": results, "count": len(results)}


@app.post("/v1/discover/skill")
def discover_skill(body: DiscoverSkillRequest) -> dict[str, Any]:
    """Phase 6 dynamic discovery: skill → providers → candidates."""
    agents = []
    try:
        # Prefer live registry listing via gateway-shaped installed agents
        agents = marketplace.list_agents()
    except Exception:  # noqa: BLE001
        agents = []
    return marketplace.discover_by_skill(
        body.skill,
        version_constraint=body.version_constraint or body.version,
        agents=agents or None,
    )


@app.post("/v1/invoke/skill")
def invoke_skill(body: DiscoverSkillRequest) -> dict[str, Any]:
    """Skill discovery + scheduler selection (no hardcoded agent URL)."""
    agents = marketplace.list_agents()
    return marketplace.resolve_invocation(
        body.skill,
        version_constraint=body.version_constraint or body.version,
        agents=agents or None,
        scheduling=scheduling,
    )


@app.get("/v1/marketplace/stats")
def marketplace_stats() -> dict[str, Any]:
    return {"stats": marketplace.stats}


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
