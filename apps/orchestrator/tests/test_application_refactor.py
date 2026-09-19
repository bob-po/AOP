"""Regression tests for Phase 35-01 application-layer split (no PG required)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from artifacts.manager import ArtifactManager
from planner.dag import PlanNode, TaskPlan
from planner.engine import PlanningEngine
from router.engine import RoutingEngine
from scheduler.engine import SchedulingEngine


def test_service_shim_exports_task_service():
    from service import TaskService

    assert TaskService.__name__ == "TaskService"
    assert TaskService.__module__ == "application.task_service"


def test_execution_worker_alias():
    from worker import ExecutionWorker
    from executor.engine import ExecutionEngine

    assert ExecutionWorker is ExecutionEngine


def test_planning_engine_delegates_to_planner():
    fake = MagicMock()
    fake.plan.return_value = SimpleNamespace(plan="p", method="heuristic", available_skills=["web-search"])
    fake.list_available_skills.return_value = ["web-search"]
    engine = PlanningEngine(planner=fake)
    out = engine.plan("goal", title="t")
    fake.plan.assert_called_once_with("goal", title="t")
    assert out.method == "heuristic"
    assert engine.list_available_skills() == ["web-search"]
    assert engine.planner is fake


def test_routing_engine_delegates_to_router():
    fake = MagicMock()
    fake.preview.return_value = {"skill": "web-search", "candidates": []}
    engine = RoutingEngine(router=fake)
    assert engine.preview("web-search")["skill"] == "web-search"
    fake.preview.assert_called_once()


def test_scheduling_engine_create_and_enqueue():
    plan = TaskPlan(
        title="t",
        goal="g",
        nodes=[PlanNode(id="a", skill="web-search")],
    )
    sched = MagicMock()
    sched.create_task.return_value = SimpleNamespace(
        task_id="tid-1",
        status="running",
        ready_jobs=[{"task_id": "tid-1", "node_key": "a", "skill": "web-search", "node_id": "n1"}],
        ready_nodes=["a"],
        nodes=[{"id": "a", "status": "ready"}],
    )
    job_queue = MagicMock()
    job_queue.enqueue.return_value = "msg-id"
    event_publisher = MagicMock()
    event_publisher.publish_node_enqueued.return_value = "event-id"
    engine = SchedulingEngine(scheduler=sched, job_queue=job_queue, event_publisher=event_publisher)
    with patch("scheduler.engine.record_task_created"):
        out = engine.create_and_enqueue(
            goal="g",
            plan=plan,
            planner_meta={"method": "heuristic", "available_skills": ["web-search"]},
            plan_source="planner",
        )
    assert out["task_id"] == "tid-1"
    assert out["enqueued_nodes"] == ["a"]
    job_queue.enqueue.assert_called_once()
    event_publisher.publish_node_enqueued.assert_called_once()


def test_scheduling_engine_approve_enqueues_ready_jobs():
    sched = MagicMock()
    sched.approve_node.return_value = {
        "status": "running",
        "ready_jobs": [{"task_id": "t1", "node_key": "b", "skill": "report-generation"}],
    }
    job_queue = MagicMock()
    job_queue.enqueue.return_value = "msg-id"
    event_publisher = MagicMock()
    event_publisher.publish_node_enqueued.return_value = "event-id"
    engine = SchedulingEngine(scheduler=sched, job_queue=job_queue, event_publisher=event_publisher)
    out = engine.approve("t1", node_key="hitl")
    assert out["enqueued_nodes"] == ["b"]
    job_queue.enqueue.assert_called_once()


def test_artifact_manager_merges_by_uri():
    store = MagicMock()
    store.list_task_artifacts.return_value = [
        {"uri": "s3://b/a", "name": "output.txt", "source": "minio"},
    ]
    scheduler = MagicMock()
    scheduler.get_task.return_value = {"nodes": [{"id": "n1"}]}
    scheduler.get_node.return_value = {
        "output_json": {
            "artifacts": [
                {"uri": "s3://b/a", "name": "output.txt", "type": "text", "size": 10},
                {"uri": "s3://b/b", "name": "output.json", "type": "json"},
            ]
        }
    }
    mgr = ArtifactManager(store=store, scheduler=scheduler)
    items = mgr.list_for_task("tid")
    uris = {i["uri"] for i in items}
    assert uris == {"s3://b/a", "s3://b/b"}
    merged = next(i for i in items if i["uri"] == "s3://b/a")
    assert merged["source"] == "minio"
    assert merged["size"] == 10


def test_task_manager_create_pipeline():
    from application.task_manager import TaskManager

    planning = MagicMock()
    planning.plan.return_value = SimpleNamespace(
        plan=TaskPlan(title="t", goal="hello", nodes=[PlanNode(id="a", skill="web-search")]),
        method="heuristic",
        available_skills=["web-search"],
    )
    scheduling = MagicMock()
    scheduling.create_and_enqueue.return_value = {
        "task_id": "tid-x",
        "status": "running",
        "enqueued_nodes": ["a"],
    }
    quotas = MagicMock(spec=["assert_can_create_task"])
    memory = MagicMock()
    mgr = TaskManager(
        planning=planning,
        scheduling=scheduling,
        quotas=quotas,
        memory=memory,
        artifacts=MagicMock(),
        workflows=MagicMock(),
    )
    out = mgr.create("hello", title="t")
    quotas.assert_can_create_task.assert_called_once()
    planning.plan.assert_called_once_with("hello", title="t")
    scheduling.create_and_enqueue.assert_called_once()
    memory.remember_goal.assert_called_once()
    assert out["task_id"] == "tid-x"
