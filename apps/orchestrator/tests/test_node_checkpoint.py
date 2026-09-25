"""Node-level checkpoints + replay_from_node."""

from __future__ import annotations

from planner.dag import PlanNode, TaskPlan
from scheduler import Scheduler
from scheduler.engine import SchedulingEngine
from tests.conftest import requires_pg


@requires_pg
def test_mark_success_writes_checkpoint(database_url: str, agent_id: str):
    sched = Scheduler(database_url=database_url)
    plan = TaskPlan(
        title="ckpt",
        goal="ckpt",
        nodes=[PlanNode(id="search", skill="web-search")],
    )
    result = sched.create_task(goal="ckpt", plan=plan)
    task_id = result.task_id
    assert sched.claim_running(task_id, "search", agent_id, attempt=1)
    sched.mark_success(
        task_id,
        "search",
        output={
            "text": "hello",
            "artifacts": [{"name": "output.txt", "uri": "s3://b/t/search/output.txt"}],
            "handoff": {
                "from": "search",
                "to": [],
                "reason": "done",
                "artifact_ids": ["s3://b/t/search/output.txt"],
                "confidence": 0.9,
            },
        },
    )
    ckpts = sched.list_checkpoints(task_id, node_key="search")
    assert len(ckpts) >= 1
    assert ckpts[0]["status"] == "success"
    assert ckpts[0]["snapshot_json"]["artifact_ids"]


@requires_pg
def test_mark_failure_writes_checkpoint_then_replay(database_url: str, agent_id: str):
    sched = Scheduler(database_url=database_url)
    plan = TaskPlan(
        title="ckpt-fail",
        goal="ckpt",
        nodes=[
            PlanNode(id="search", skill="web-search"),
            PlanNode(id="report", skill="report-generation", depends_on=["search"]),
        ],
    )
    result = sched.create_task(goal="ckpt", plan=plan)
    task_id = result.task_id
    assert sched.claim_running(task_id, "search", agent_id, attempt=1)
    decision = sched.mark_failure(
        task_id, "search", error="boom", attempt=3, agent_id=agent_id
    )
    assert decision["decision"] == "failed"
    ckpts = sched.list_checkpoints(task_id, node_key="search")
    assert any(c["status"] == "failed" for c in ckpts)

    replayed = sched.replay_from_node(task_id, "search", clear_downstream=True)
    assert replayed["replayed"] is True
    assert replayed["next_attempt"] >= 4
    assert "report" in (replayed.get("cleared_downstream") or [])
    assert len(replayed["ready_jobs"]) == 1
    assert replayed["ready_jobs"][0]["node_key"] == "search"
    search = sched.get_node(task_id, "search")
    assert search is not None
    assert search["status"] == "retrying"
    report = sched.get_node(task_id, "report")
    assert report is not None
    assert report["status"] == "pending"


@requires_pg
def test_scheduling_engine_replay_enqueues(database_url: str, agent_id: str):
    sched = Scheduler(database_url=database_url)
    plan = TaskPlan(
        title="ckpt-eng",
        goal="ckpt",
        nodes=[PlanNode(id="search", skill="web-search")],
    )
    result = sched.create_task(goal="ckpt", plan=plan)
    task_id = result.task_id
    assert sched.claim_running(task_id, "search", agent_id, attempt=1)
    sched.mark_failure(task_id, "search", error="x", attempt=3, agent_id=agent_id)

    enqueued: list[dict] = []

    class FakeQueue:
        def enqueue(self, **job):
            enqueued.append(job)
            return "msg"

    class FakePub:
        def publish_node_enqueued(self, *a, **k):
            return "ev"

    engine = SchedulingEngine(
        scheduler=sched, job_queue=FakeQueue(), event_publisher=FakePub()
    )
    out = engine.replay_from_node(task_id, "search")
    assert out["enqueued_nodes"] == ["search"]
    assert enqueued and enqueued[0]["node_key"] == "search"
