"""TaskService: application facade for HTTP / API consumers."""

from __future__ import annotations

from typing import Any

from artifacts import ArtifactStore
from artifacts.manager import ArtifactManager
from billing import BillingService
from billing.invoice import InvoiceService
from evaluation import EvaluationService
from egress import EgressService
from memory import MemoryService
from observability import MetricsService
from planner.engine import PlanningEngine
from quota import QuotaService
from router.engine import RoutingEngine
from runtime_graph import RuntimeGraphService
from scheduler.engine import SchedulingEngine
from streams import StreamClient
from workflows import WorkflowService
from aggregator import Aggregator

from .task_manager import TaskManager


class TaskService:
    """Facade over domain engines — method signatures match legacy service.TaskService."""

    def __init__(self) -> None:
        self.planner_engine = PlanningEngine()
        self.planner = self.planner_engine.planner
        self.router_engine = RoutingEngine()
        self.router = self.router_engine.router
        self.runtime_graph = RuntimeGraphService()
        self.streams = StreamClient()
        self.artifact_store = ArtifactStore()
        self.artifacts = self.artifact_store  # legacy attribute name
        self.workflows = WorkflowService()
        self.evaluations = EvaluationService()
        self.aggregator = Aggregator()
        self.memory = MemoryService()
        self.metrics = MetricsService()
        self.billing = BillingService()
        self.invoices = InvoiceService(billing=self.billing)
        self.quotas = QuotaService(billing=self.billing)
        self.egress = EgressService()

        self.scheduling = SchedulingEngine()
        self.scheduler = self.scheduling.scheduler
        self.artifact_manager = ArtifactManager(
            store=self.artifact_store,
            scheduler=self.scheduler,
        )
        self.tasks = TaskManager(
            planning=self.planner_engine,
            scheduling=self.scheduling,
            workflows=self.workflows,
            quotas=self.quotas,
            memory=self.memory,
            artifacts=self.artifact_manager,
        )

    # ── lifecycle (TaskManager) ──────────────────────────────────────────

    def create(
        self,
        content: str,
        *,
        title: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return self.tasks.create(content, title=title, tenant_id=tenant_id)

    def run_workflow(
        self,
        workflow_id: str,
        *,
        content: str,
        title: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return self.tasks.run_workflow(
            workflow_id, content=content, title=title, tenant_id=tenant_id
        )

    def get(self, task_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        return self.tasks.get(task_id, tenant_id=tenant_id)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.tasks.list(status=status, limit=limit, tenant_id=tenant_id)

    def cancel(self, task_id: str) -> dict[str, Any] | None:
        return self.tasks.cancel(task_id)

    def approve(
        self,
        task_id: str,
        *,
        node_key: str | None = None,
    ) -> dict[str, Any]:
        return self.tasks.approve(task_id, node_key=node_key)

    def reject(
        self,
        task_id: str,
        *,
        node_key: str | None = None,
        reason: str = "rejected by user",
    ) -> dict[str, Any]:
        return self.tasks.reject(task_id, node_key=node_key, reason=reason)

    def overview(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.tasks.overview(tenant_id=tenant_id)

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return self.tasks.events(task_id)

    def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        return self.tasks.list_artifacts(task_id)

    def list_all_artifacts(
        self,
        *,
        task_id: str | None = None,
        type_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.tasks.list_all_artifacts(
            task_id=task_id, type_filter=type_filter, limit=limit
        )

    # ── router ───────────────────────────────────────────────────────────

    def router_preview(self, skill: str) -> dict[str, Any]:
        return self.router_engine.preview(skill)

    def discover(self, **kwargs: Any) -> dict[str, Any]:
        """A2A OS: capability-aware Agent discovery (callable by any Agent)."""
        return self.router_engine.discover(**kwargs)

    def route(self, **kwargs: Any) -> dict[str, Any]:
        """A2A OS: select the best Agent for a request (callable by any Agent)."""
        return self.router_engine.route(**kwargs)

    # ── runtime execution graph ──────────────────────────────────────────

    def record_runtime_edge(self, **kwargs: Any) -> dict[str, Any]:
        """A2A OS: record an Agent-to-Agent call edge in the runtime graph."""
        return self.runtime_graph.record_edge(**kwargs)

    def runtime_graph_view(self, root_task_id: str) -> dict[str, Any]:
        """A2A OS: reconstruct the runtime execution graph for a root task."""
        return self.runtime_graph.get_graph(root_task_id)

    def collaboration_graph_view(self, root_task_id: str) -> dict[str, Any]:
        """A2A OS: frontend-friendly collaboration graph (nodes + links)."""
        return self.runtime_graph.collaboration_graph(root_task_id)

    def get_with_graph(self, task_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        """Central Task plus associated runtime collaboration graph (Phase 2)."""
        row = self.tasks.get(task_id, tenant_id=tenant_id)
        if not row:
            return None
        try:
            graph = self.runtime_graph.collaboration_graph(task_id)
        except Exception:  # noqa: BLE001 - graph is best-effort enrichment
            graph = {
                "root_task_id": task_id,
                "kind": "collaboration_graph",
                "nodes": [],
                "links": [],
                "tree": [],
                "edges": [],
            }
        out = dict(row)
        out["collaboration_graph"] = graph
        out["runtime_graph"] = self.runtime_graph.get_graph(task_id)
        return out

    def agent_performance(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.router_engine.agent_performance(limit=limit)

    # ── evaluation ───────────────────────────────────────────────────────

    def evaluate(self, task_id: str, *, method: str = "heuristic") -> dict[str, Any]:
        return self.evaluations.evaluate(task_id, method=method)

    def get_evaluation(self, task_id: str) -> dict[str, Any] | None:
        return self.evaluations.get_for_task(task_id)

    def list_evaluations(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 50,
        min_score: float | None = None,
    ) -> list[dict[str, Any]]:
        return self.evaluations.list(tenant_id=tenant_id, limit=limit, min_score=min_score)

    def evaluation_overview(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.evaluations.overview(tenant_id=tenant_id)

    # ── memory ───────────────────────────────────────────────────────────

    def list_memory(self, task_id: str) -> list[dict[str, Any]]:
        return self.memory.list_for_task(task_id)

    def put_memory(
        self,
        task_id: str,
        memory_key: str,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.memory.put(task_id, memory_key, content, metadata=metadata)

    def delete_memory(self, task_id: str, memory_key: str) -> bool:
        return self.memory.delete(task_id, memory_key)

    def list_tenant_memory(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.memory.list_tenant(limit=limit)

    def put_tenant_memory(
        self,
        memory_key: str,
        content: str,
        *,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.memory.put_tenant(
            memory_key,
            content,
            title=title,
            metadata=metadata,
        )

    def search_tenant_memory(self, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        return self.memory.search_tenant(query, top_k=top_k)

    def delete_tenant_memory(self, memory_key: str) -> bool:
        return self.memory.delete_tenant(memory_key)

    def promote_task_memory(self, task_id: str) -> list[dict[str, Any]]:
        return self.memory.promote_task(task_id)

    # ── metrics / billing / quota / egress ───────────────────────────────

    def metrics_snapshot(self, *, hours: float = 24) -> dict[str, Any]:
        return self.metrics.snapshot(hours=hours)

    def metrics_prometheus(self, *, hours: float = 24) -> str:
        return self.metrics.prometheus_text(hours=hours)

    def billing_usage(self, *, days: int = 30, tenant_id: str | None = None) -> dict[str, Any]:
        return self.billing.usage(days=days, tenant_id=tenant_id)

    def billing_summary(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.billing.summary(tenant_id=tenant_id)

    def invoice_preview(self, *, days: int = 30, tenant_id: str | None = None) -> dict[str, Any]:
        return self.invoices.preview(days=days, tenant_id=tenant_id)

    def invoice_preview_markdown(self, *, days: int = 30, tenant_id: str | None = None) -> str:
        return self.invoices.preview_markdown(days=days, tenant_id=tenant_id)

    def create_invoice(
        self, *, days: int = 30, tenant_id: str | None = None, status: str = "draft"
    ) -> dict[str, Any]:
        return self.invoices.create(days=days, tenant_id=tenant_id, status=status)

    def list_invoices(self, *, tenant_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return self.invoices.list(tenant_id=tenant_id, limit=limit)

    def get_invoice(self, invoice_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        return self.invoices.get(invoice_id, tenant_id=tenant_id)

    def create_checkout(
        self,
        invoice_id: str,
        *,
        tenant_id: str | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        return self.invoices.create_checkout(
            invoice_id, tenant_id=tenant_id, dry_run=dry_run
        )

    def list_checkouts(
        self, *, tenant_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.invoices.list_checkouts(tenant_id=tenant_id, limit=limit)

    def list_quota_grants(
        self, *, tenant_id: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.quotas.list_grants(tenant_id=tenant_id, limit=limit)

    def handle_stripe_webhook(
        self, payload: bytes, sig_header: str | None
    ) -> dict[str, Any]:
        return self.invoices.handle_stripe_webhook(payload, sig_header)

    def simulate_checkout_paid(self, stripe_session_id: str) -> dict[str, Any]:
        return self.invoices.simulate_checkout_paid(stripe_session_id)

    def quota_status(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.quotas.status(tenant_id=tenant_id)

    def get_quota(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.quotas.get(tenant_id=tenant_id)

    def update_quota(self, *, tenant_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.quotas.upsert(tenant_id=tenant_id, **kwargs)

    def egress_policy(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.egress.get(tenant_id=tenant_id)

    def update_egress(self, *, tenant_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        return self.egress.upsert(tenant_id=tenant_id, **kwargs)

    def check_egress(self, url: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.egress.check_url(url, tenant_id=tenant_id)
