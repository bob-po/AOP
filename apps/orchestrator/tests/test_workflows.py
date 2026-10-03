"""Workflow DAG → plan keeps approval gates."""

from __future__ import annotations

from workflows import WorkflowService


def test_dag_to_plan_keeps_peer_approval(monkeypatch):
    monkeypatch.setattr("workflows.hitl_skills", lambda: set())
    svc = WorkflowService.__new__(WorkflowService)
    plan = WorkflowService._dag_to_plan(
        svc,
        {
            "nodes": [
                {
                    "id": "run",
                    "skill": "deepseek-harness",
                    "approval_mode": "agent",
                    "approver_agent": "claude-code",
                },
                {
                    "id": "report",
                    "skill": "pi",
                    "depends_on": ["run"],
                    "approval_mode": "both",
                    "approver_agent": "claude-code",
                },
            ]
        },
        goal="research",
        title="gated",
    )
    by_id = {n.id: n for n in plan.nodes}
    assert by_id["run"].approval_mode == "agent"
    assert by_id["run"].approver_agent == "claude-code"
    assert by_id["report"].approval_mode == "both"
    assert by_id["report"].requires_approval is True


def test_dag_to_plan_hitl_skill_still_system(monkeypatch):
    monkeypatch.setattr("workflows.hitl_skills", lambda: {"report-generation"})
    svc = WorkflowService.__new__(WorkflowService)
    plan = WorkflowService._dag_to_plan(
        svc,
        {"nodes": [{"id": "r", "skill": "report-generation"}]},
        goal="g",
        title="t",
    )
    assert plan.nodes[0].requires_approval is True
