"""TaskManager: application use-cases for task lifecycle."""

from __future__ import annotations

import os
from typing import Any

from artifacts.manager import ArtifactManager
from memory import MemoryService
from planner.dag import TaskPlan, validate_plan
from planner.engine import PlanningEngine
from quota import QuotaService
from scheduler import DEFAULT_TENANT_ID
from scheduler.engine import SchedulingEngine
from workflows import WorkflowService


def _tenant_memory_enabled() -> bool:
    return os.getenv("TENANT_MEMORY_RECALL", "1").lower() not in {"0", "false", "no", "off"}


class TaskManager:
    """Orchestrates plan → schedule → enqueue and HITL decisions."""

    def __init__(
        self,
        *,
        planning: PlanningEngine | None = None,
        scheduling: SchedulingEngine | None = None,
        workflows: WorkflowService | None = None,
        quotas: QuotaService | None = None,
        memory: MemoryService | None = None,
        artifacts: ArtifactManager | None = None,
    ) -> None:
        self.planning = planning or PlanningEngine()
        self.scheduling = scheduling or SchedulingEngine()
        self.workflows = workflows or WorkflowService()
        self.quotas = quotas or QuotaService()
        self.memory = memory or MemoryService()
        self.artifacts = artifacts or ArtifactManager(
            store=None,
            scheduler=self.scheduling.scheduler,
        )

    def create(
        self,
        content: str,
        *,
        title: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        self.quotas.assert_can_create_task(tenant_id=tenant_id or DEFAULT_TENANT_ID)
        result = self.planning.plan(content, title=title)
        scheduled = self.scheduling.create_and_enqueue(
            goal=content,
            plan=result.plan,
            planner_meta={
                "method": result.method,
                "available_skills": result.available_skills,
            },
            plan_source="planner",
            tenant_id=tenant_id,
        )
        self._remember_goal(scheduled["task_id"], content, tenant_id=tenant_id)
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
        plan: TaskPlan = self.workflows.build_plan(workflow_id, goal=content, title=title)
        available = set(self.planning.list_available_skills())
        validate_plan(plan, available_skills=available)
        scheduled = self.scheduling.create_and_enqueue(
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
        self._remember_goal(scheduled["task_id"], content, tenant_id=tenant_id)
        return scheduled

    def get(self, task_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        return self.scheduling.get_task(task_id, tenant_id=tenant_id)

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 50,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.scheduling.list_tasks(status=status, limit=limit, tenant_id=tenant_id)

    def cancel(self, task_id: str) -> dict[str, Any] | None:
        return self.scheduling.cancel_task(task_id)

    def approve(
        self,
        task_id: str,
        *,
        node_key: str | None = None,
    ) -> dict[str, Any]:
        return self.scheduling.approve(task_id, node_key=node_key)

    def reject(
        self,
        task_id: str,
        *,
        node_key: str | None = None,
        reason: str = "rejected by user",
    ) -> dict[str, Any]:
        return self.scheduling.reject(task_id, node_key=node_key, reason=reason)

    def overview(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        return self.scheduling.overview_stats(tenant_id=tenant_id)

    def events(self, task_id: str) -> list[dict[str, Any]]:
        return self.scheduling.list_events(task_id)

    def list_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        return self.artifacts.list_for_task(task_id)

    def list_all_artifacts(
        self,
        *,
        task_id: str | None = None,
        type_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.artifacts.list_all(
            task_id=task_id,
            type_filter=type_filter,
            limit=limit,
        )

    def _remember_goal(
        self,
        task_id: str,
        content: str,
        *,
        tenant_id: str | None,
    ) -> None:
        tid = tenant_id or DEFAULT_TENANT_ID
        try:
            self.memory.remember_goal(task_id, content, tenant_id=tid)
            if _tenant_memory_enabled():
                self.memory.recall_into_task(task_id, content, tenant_id=tid)
        except Exception:  # noqa: BLE001
            pass
