"""Planner heuristic tests — unified claude-code agent."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from planner import Planner
from planner.dag import DAGValidationError


AGENTS = {"claude-code"}


@pytest.fixture
def planner() -> Planner:
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=sorted(AGENTS)):
        yield p


def _plan(planner: Planner, goal: str, *, hitl: str = "off"):
    with patch.object(planner, "list_available_agents", return_value=sorted(AGENTS)):
        with patch.dict(
            os.environ,
            {"HITL_SKILLS": hitl, "PLANNER_V2": "1", "PLANNER_MULTI_STEP": "0"},
            clear=False,
        ):
            return planner.plan(goal)


def test_any_goal_goes_to_claude_code(planner: Planner):
    result = _plan(planner, "搜索 OpenAI 最新消息")
    assert result.method == "heuristic"
    assert len(result.plan.nodes) == 1
    assert result.plan.nodes[0].id == "run"
    assert result.plan.nodes[0].skill == "claude-code"


def test_code_goal_also_claude_code(planner: Planner):
    result = _plan(planner, "帮我写一个 python 函数实现快速排序")
    assert result.plan.nodes[0].skill == "claude-code"


def test_no_agents_raises():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=[]):
        with pytest.raises(ValueError, match="no online agents"):
            p.plan("anything")


def test_fallback_claude_code():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=["claude-code"]):
        with patch.object(p, "_heuristic_nodes", return_value=[]):
            result = p.plan("noop")
    assert result.method == "fallback"
    assert result.plan.nodes[0].skill == "claude-code"


def test_plan_rejects_unknown_agent():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=["claude-code"]):
        from planner.dag import PlanNode

        bad = [PlanNode(id="a", skill="missing-agent")]
        with patch.object(p, "_heuristic_nodes", return_value=bad):
            with pytest.raises(DAGValidationError):
                p.plan("x")
