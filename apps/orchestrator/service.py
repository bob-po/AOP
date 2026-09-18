"""Task service: plan + schedule + enqueue + workflow facade."""

from __future__ import annotations

import os
from typing import Any

from artifacts import ArtifactStore
from billing import BillingService
from billing.invoice import InvoiceService
from evaluation import EvaluationService
from memory import MemoryService
from observability import MetricsService, record_task_created
from planner import Planner
from planner.dag import TaskPlan
from quota import QuotaExceeded, QuotaService
from egress import EgressService
from router import AgentRouter
from scheduler import DEFAULT_TENANT_ID, Scheduler
from streams import StreamClient
from workflows import WorkflowService
from aggregator import Aggregator


def _tenant_memory_enabled() -> bool:
    return os.getenv("TENANT_MEMORY_RECALL", "1").lower() not in {"0", "false", "no", "off"}


def _tenant_memory_promote() -> bool:
    return os.getenv("TENANT_MEMORY_PROMOTE", "1").lower() not in {"0", "false", "no", "off"}


class TaskService:
    def __init__(self) -> None:
        self.planner = Planner()
        self.scheduler = Scheduler()
        self.streams = StreamClient()
        self.artifacts = ArtifactStore()
        self.workflows = WorkflowService()
        self.evaluations = EvaluationService()
        self.router = AgentRouter()
        self.aggregator = Aggregator()
        self.memory = MemoryService()
        self.metrics = MetricsService()
        self.billing = BillingService()
        self.invoices = InvoiceService(billing=self.billing)
        self.quotas = QuotaService(billing=self.billing)
        self.egress = EgressService()

    def create(
        self,
        content: str,
        *,
        title: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        self.quotas.assert_can_create_task(tenant_id=tenant_id or DEFAULT_TENANT_ID)
        result = self.planner.plan(content, title=title)
        scheduled = self._schedule_and_enqueue(
            goal=content,
            plan=result.plan,
            planner_meta={
                "method": result.method,
                "available_skills": result.available_skills,
            },
            plan_source="planner",
            tenant_id=tenant_id,
        )
        try:
            self.memory.remember_goal(
                scheduled["task_id"],
                content,
                tenant_id=tenant_id or DEFAULT_TENANT_ID,
            )
            if _tenant_memory_enabled():
                self.memory.recall_into_task(
                    scheduled["task_id"],
                    content,
                    tenant_id=tenant_id or DEFAULT_TENANT_ID,
                )
        except Exception:  # noqa: BLE001
            pass
        return scheduled

    def run_workflow(
        self,
        workflow_id: str,
        *,
        content: str,
        title: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        content = (content or "").strip()
        if not content:
            raise ValueError("input.content is required")
        self.quotas.assert_can_create_task(tenant_id=tenant_id or DEFAULT_TENANT_ID)
        wf = self.workflows.get(workflow_id)
        if not wf:
            raise ValueError(f"workflow not found: {workflow_id}")
        plan = self.workflows.build_plan(workflow_id, goal=content, title=title)
        available = set(self.planner.list_available_skills())
        from planner.dag import validate_plan

        validate_plan(plan, available_skills=available)
        scheduled = self._schedule_and_enqueue(
            goal=content,
            plan=plan,
            planner_meta={
                "method": "workflow",
                "workflow_id": wf["workflow_id"],
                "workflow_key": wf["workflow_key"],
                "available_skills": sorted(available),
            },
            plan_source="workflow",
            workflow_id=wf["workflow_id"],
            tenant_id=tenant_id,
        )
        try:
            self.memory.remember_goal(
                scheduled["task_id"],
                content,
                tenant_id=tenant_id or DEFAULT_TENANT_ID,
            )
            if _tenant_memory_enabled():
                self.memory.recall_into_task(
                    scheduled["task_id"],
                    content,
                    tenant_id=tenant_id or DEFAULT_TENANT_ID,
                )
        except Exception:  # noqa: BLE001
            pass
        return scheduled

    def _schedule_and_enqueue(
        self,
        *,
        goal: str,
        plan: TaskPlan,
        planner_meta: dict[str, Any],
        plan_source: str,
        workflow_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        scheduled = self.scheduler.create_task(
            goal=goal,
            plan=plan,
            workflow_id=workflow_id,
            plan_source=plan_source,
            tenant_id=tenant_id or DEFAULT_TENANT_ID,
        )
        enqueued: list[str] = []
        for job in scheduled.ready_jobs:
            self.streams.enqueue_execution(**job)
            enqueued.append(job["node_key"])
            self.streams.publish_task_event(
                "task.node.enqueued",
                {
                    "task_id": scheduled.task_id,
                    "node_key": job["node_key"],
                    "skill": job["skill"],
                },
            )
        try:
            record_task_created(str(scheduled.status or "running"))
        except Exception:  # noqa: BLE001
            pass
        return {
            "task_id": scheduled.task_id,
            "status": scheduled.status,
            "title": plan.title,
            "workflow_id": workflow_id,
            "planner": planner_meta,
            "plan": plan.to_dict(),
            "ready_nodes": scheduled.ready_nodes,
            "enqueued_nodes": enqueued,
            "nodes": scheduled.nodes,
        }

    def get(self, task_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        return self.scheduler.get_task(task_id, tenant_id=tenant_id)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.scheduler.list_tasks(status=status, limit=limit, tenant_id=tenant_id)

    def cancel(self, task_id: str) -> dict[str, Any] | None:
        row = self.scheduler.cancel_task(task_id)
        if row and row.get("cancelled") is True:
            try:
                ev = self.evaluations.evaluate(task_id)
                row = {**row, "evaluation": ev}
            except Exception:  # noqa: BLE001
                pass
        return row

    def approve(
        self,
        task_id: str,
        *,
        node_key: str | None = None,
    ) -> dict[str, Any]:
        result = self.scheduler.approve_node(task_id, node_key)
        enqueued: list[str] = []
        for job in result.get("ready_jobs") or []:
            self.streams.enqueue_execution(**job)
            enqueued.append(job["node_key"])
            self.streams.publish_task_event(
                "task.node.enqueued",
                {
                    "task_id": task_id,
                    "node_key": job["node_key"],
                    "skill": job["skill"],
                },
            )
        result["enqueued_nodes"] = enqueued
        if result.get("status") == "completed":
            try:
                result_json = self.aggregator.build_result(task_id)
                self.streams.publish_task_event(
                    "task.completed",
                    {"task_id": task_id, "summary_len": len(result_json.get("summary") or "")},
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                result["evaluation"] = self.evaluations.evaluate(task_id)
            except Exception:  # noqa: BLE001
                pass
        return result

    def reject(
        self,
        task_id: str,
        *,
        node_key: str | None = None,
        reason: str = "rejected by user",
    ) -> dict[str, Any]:
        result = self.scheduler.reject_node(task_id, node_key=node_key, reason=reason)
        try:
            result["evaluation"] = self.evaluations.evaluate(task_id)
        except Exception:  # noqa: BLE001
            pass
        return result

    def router_preview(self, skill: str) -> dict[str, Any]:
        return self.router.preview(skill)

    def agent_performance(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.router.agent_performance(limit=limit)

    def overview(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.scheduler.overview_stats(tenant_id=tenant_id)

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return self.scheduler.list_events(task_id)

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

    def list_all_artifacts(
        self,
        *,
        task_id: str | None = None,
        type_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.artifacts.list_all_artifacts(
            task_id=task_id,
            type_filter=type_filter,
            limit=limit,
        )

    def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        stored = self.artifacts.list_task_artifacts(task_id)
        task = self.scheduler.get_task(task_id)
        if not task:
            return stored
        meta_from_nodes: list[dict[str, Any]] = []
        for n in task.get("nodes") or []:
            detail = self.scheduler.get_node(task_id, n["id"])
            if not detail:
                continue
            out = detail.get("output_json") or {}
            if isinstance(out, str):
                import json

                out = json.loads(out)
            if not isinstance(out, dict):
                continue
            for art in out.get("artifacts") or []:
                meta_from_nodes.append(
                    {
                        "node_id": n["id"],
                        "name": art.get("name"),
                        "type": art.get("type"),
                        "uri": art.get("uri"),
                        "mime_type": art.get("mime_type"),
                        "size": art.get("size"),
                        "source": "node_output",
                    }
                )
        by_uri: dict[str, dict[str, Any]] = {}
        for item in meta_from_nodes + stored:
            uri = item.get("uri")
            if not uri:
                continue
            by_uri[uri] = {**by_uri.get(uri, {}), **item}
        return list(by_uri.values())
