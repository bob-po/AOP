"""Unit tests for Task DAG validation and ready-node selection."""

from __future__ import annotations

import pytest

from planner.dag import (
    DAGValidationError,
    PlanNode,
    TaskPlan,
    ready_node_ids,
    validate_plan,
)


def _plan(*nodes: PlanNode, title: str = "t", goal: str = "g") -> TaskPlan:
    return TaskPlan(title=title, goal=goal, nodes=list(nodes))


def test_validate_ok_linear_dag():
    plan = _plan(
        PlanNode(id="a", skill="web-search"),
        PlanNode(id="b", skill="knowledge-search", depends_on=["a"]),
        PlanNode(id="c", skill="report-generation", depends_on=["b"]),
    )
    validate_plan(plan, available_skills={"web-search", "knowledge-search", "report-generation"})


def test_validate_ok_parallel_roots():
    plan = _plan(
        PlanNode(id="search", skill="web-search"),
        PlanNode(id="rag", skill="knowledge-search"),
        PlanNode(id="analysis", skill="business-analysis", depends_on=["search", "rag"]),
    )
    validate_plan(
        plan,
        available_skills={"web-search", "knowledge-search", "business-analysis"},
    )


def test_reject_empty_plan():
    with pytest.raises(DAGValidationError, match="at least one node"):
        validate_plan(_plan())


def test_reject_duplicate_ids():
    with pytest.raises(DAGValidationError, match="unique"):
        validate_plan(
            _plan(
                PlanNode(id="a", skill="web-search"),
                PlanNode(id="a", skill="knowledge-search"),
            )
        )


def test_reject_unknown_dependency():
    with pytest.raises(DAGValidationError, match="unknown node"):
        validate_plan(
            _plan(PlanNode(id="a", skill="web-search", depends_on=["missing"]))
        )


def test_reject_self_dependency():
    with pytest.raises(DAGValidationError, match="cannot depend on itself"):
        validate_plan(_plan(PlanNode(id="a", skill="web-search", depends_on=["a"])))


def test_reject_cycle():
    with pytest.raises(DAGValidationError, match="cycle"):
        validate_plan(
            _plan(
                PlanNode(id="a", skill="web-search", depends_on=["b"]),
                PlanNode(id="b", skill="knowledge-search", depends_on=["a"]),
            )
        )


def test_reject_unavailable_skill():
    with pytest.raises(DAGValidationError, match="not available"):
        validate_plan(
            _plan(PlanNode(id="a", skill="web-search")),
            available_skills={"knowledge-search"},
        )


def test_ready_node_ids_unlocks_after_deps():
    nodes = [
        PlanNode(id="a", skill="web-search"),
        PlanNode(id="b", skill="knowledge-search"),
        PlanNode(id="c", skill="business-analysis", depends_on=["a", "b"]),
    ]
    pending = {"a", "b", "c"}
    assert set(ready_node_ids(nodes, completed=set(), pending=pending)) == {"a", "b"}

    pending = {"c"}
    assert ready_node_ids(nodes, completed={"a"}, pending=pending) == []
    assert ready_node_ids(nodes, completed={"a", "b"}, pending=pending) == ["c"]


def test_plan_roundtrip_dict():
    plan = _plan(
        PlanNode(id="a", skill="web-search", requires_approval=True),
        PlanNode(id="b", skill="report-generation", depends_on=["a"]),
    )
    restored = TaskPlan.from_dict(plan.to_dict())
    assert restored.title == plan.title
    assert restored.nodes[0].requires_approval is True
    assert restored.nodes[1].depends_on == ["a"]
