"""Planner heuristic tests — unified claude-code agent."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from planner import (
    Planner,
    dispatch_agent_instruction,
    extract_work_goal,
    wants_all_agents,
)
from planner.dag import DAGValidationError


AGENTS = {"claude-code"}
ALL_AGENTS = {"claude-code", "deepseek-harness", "pi"}


@pytest.fixture
def planner() -> Planner:
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=sorted(AGENTS)):
        with patch.object(p, "list_ready_agents", return_value=sorted(AGENTS)):
            yield p


def _plan(
    planner: Planner,
    goal: str,
    *,
    hitl: str = "off",
    agents: set[str] | None = None,
    ready: set[str] | None = None,
):
    online = sorted(agents if agents is not None else AGENTS)
    ready_keys = sorted(ready if ready is not None else online)
    with patch.object(planner, "list_available_agents", return_value=online):
        with patch.object(planner, "list_ready_agents", return_value=ready_keys):
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


def test_wants_all_agents_markers():
    assert wants_all_agents("用目前所有的agent调研 ui2v")
    assert wants_all_agents("请使用全部 agent 完成调研")
    assert wants_all_agents("use all agents to research X")
    assert not wants_all_agents("搜索 OpenAI 最新消息")


def test_extract_work_goal_strips_routing_preamble():
    assert "所有" not in extract_work_goal(
        "使用目前所有的agent，调研ui2v这个网页，整理公开资料并输出研究摘要"
    )
    work = extract_work_goal(
        "使用目前所有的agent，调研ui2v这个网页，整理公开资料并输出研究摘要"
    )
    assert "ui2v" in work
    assert "研究摘要" in work
    assert "agent" not in work.lower()


def test_dispatch_brief_contains_work_not_routing():
    brief = dispatch_agent_instruction(
        "claude-code",
        "调研ui2v这个网页，整理公开资料并输出研究摘要",
    )
    assert "调研ui2v" in brief
    assert "不要再 spawn" in brief or "不要再" in brief
    assert "使用目前所有" not in brief


def test_all_agents_goal_fans_out_parallel(planner: Planner):
    result = _plan(
        planner,
        "用目前所有的agent调研一下ui2v这个项目",
        agents=ALL_AGENTS,
        ready=ALL_AGENTS,
    )
    assert result.method == "heuristic_multi"
    skills = {n.skill for n in result.plan.nodes}
    assert skills == ALL_AGENTS
    assert all(n.depends_on == [] for n in result.plan.nodes)
    assert len(result.plan.nodes) == 3
    # Each agent gets a clean work brief — not the raw "用所有 agent…" sentence.
    for n in result.plan.nodes:
        assert n.instruction
        assert "ui2v" in n.instruction
        assert "用目前所有" not in n.instruction
        assert n.skill.split("-")[0] in n.instruction.lower() or "独立" in n.instruction


def test_all_agents_skips_unready_peers(planner: Planner):
    """Missing CLI/API key → runner_ready=false → only schedule Claude."""
    result = _plan(
        planner,
        "用目前所有的agent调研 ui2v",
        agents=ALL_AGENTS,
        ready={"claude-code"},
    )
    assert result.method == "heuristic_multi"
    assert len(result.plan.nodes) == 1
    assert result.plan.nodes[0].skill == "claude-code"


def test_all_agents_with_only_one_online_stays_single(planner: Planner):
    result = _plan(
        planner,
        "用目前所有的agent调研 ui2v",
        agents={"claude-code"},
        ready={"claude-code"},
    )
    assert result.method == "heuristic_multi"
    assert len(result.plan.nodes) == 1
    assert result.plan.nodes[0].skill == "claude-code"


def test_no_agents_raises():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=[]):
        with patch.object(p, "list_ready_agents", return_value=[]):
            with pytest.raises(ValueError, match="no online agents"):
                p.plan("anything")


def test_fallback_claude_code():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=["claude-code"]):
        with patch.object(p, "list_ready_agents", return_value=["claude-code"]):
            with patch.object(p, "_heuristic_nodes", return_value=[]):
                result = p.plan("noop")
    assert result.method == "fallback"
    assert result.plan.nodes[0].skill == "claude-code"


def test_plan_rejects_unknown_agent():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=["claude-code"]):
        with patch.object(p, "list_ready_agents", return_value=["claude-code"]):
            from planner.dag import PlanNode

            bad = [PlanNode(id="a", skill="missing-agent")]
            with patch.object(p, "_heuristic_nodes", return_value=bad):
                with pytest.raises(DAGValidationError):
                    p.plan("x")
