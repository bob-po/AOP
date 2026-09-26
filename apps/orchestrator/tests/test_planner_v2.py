"""Phase 19: planner JSON repair + goal decomposition."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from planner import Planner
from planner.dag import PlanNode, TaskPlan, validate_plan
from planner.decompose import decompose_to_nodes, split_goal_fragments
from planner.json_plan import extract_json_object, nodes_from_payload


# Legacy specialty skill names — still used by decompose unit tests / opt-in MULTI_STEP.
SKILLS = {
    "web-search",
    "knowledge-search",
    "business-analysis",
    "report-generation",
    "text-to-image",
    "text-to-video",
}

HARNESS = {"claude-code", "deepseek-harness", "pi"}


def test_extract_json_from_fence():
    raw = 'Sure.\n```json\n{"nodes":[{"id":"a","skill":"web-search"}]}\n```\n'
    data = extract_json_object(raw)
    assert data and data["nodes"][0]["skill"] == "web-search"


def test_nodes_from_payload_drops_bad_skills_and_deps():
    data = {
        "nodes": [
            {"id": "a", "skill": "web-search"},
            {"id": "b", "skill": "not-real", "depends_on": ["a"]},
            {"id": "c", "skill": "report-generation", "depends_on": ["a", "ghost"]},
        ]
    }
    nodes = nodes_from_payload(data, available_skills=SKILLS, hitl={"report-generation"})
    ids = {n.id for n in nodes}
    assert ids == {"a", "c"}
    c = next(n for n in nodes if n.id == "c")
    assert c.depends_on == ["a"]
    assert c.requires_approval is True
    validate_plan(TaskPlan(title="t", goal="g", nodes=nodes), available_skills=SKILLS)


def test_split_numbered_goal():
    frags = split_goal_fragments("1. 搜索竞品 2. 分析市场 3. 生成报告")
    assert len(frags) >= 3


def test_decompose_linear_steps():
    nodes = decompose_to_nodes(
        "1. 搜索竞品 2. 做业务分析 3. 生成报告",
        SKILLS,
        hitl={"report-generation"},
    )
    assert len(nodes) >= 3
    assert nodes[0].depends_on == []
    assert nodes[1].depends_on == [nodes[0].id]
    assert nodes[-1].skill == "report-generation"
    assert nodes[-1].requires_approval is True


def test_planner_v2_steps_method():
    """MULTI_STEP + specialty skills still available → linear DAG."""
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=sorted(SKILLS)):
        with patch.dict(
            os.environ,
            {
                "PLANNER_V2": "1",
                "PLANNER_MULTI_STEP": "1",
                "HITL_SKILLS": "report-generation",
            },
            clear=False,
        ):
            result = p.plan("1. 搜索资料 2. 分析一下 3. 生成报告")
    assert result.method == "heuristic_steps"
    assert len(result.plan.nodes) >= 3


def test_planner_llm_invalid_falls_back_to_heuristic():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=sorted(HARNESS)):
        with patch.dict(
            os.environ,
            {
                "PLANNER_LLM": "true",
                "PLANNER_V2": "1",
                "PLANNER_MULTI_STEP": "0",
                "HITL_SKILLS": "off",
            },
            clear=False,
        ):
            with patch.object(
                p,
                "_try_llm_nodes",
                return_value=(
                    [PlanNode(id="x", skill="missing-skill")],
                    False,
                ),
            ):
                result = p.plan("帮我研究一个 AI 产品并生成报告")
    assert result.method == "heuristic"
    assert result.plan.nodes[0].skill == "claude-code"


def test_research_goal_still_heuristic_pipeline():
    """Harness-first: research goals are a single hop to the default agent."""
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_agents", return_value=sorted(HARNESS)):
        with patch.dict(
            os.environ,
            {
                "PLANNER_V2": "1",
                "PLANNER_MULTI_STEP": "0",
                "HITL_SKILLS": "off",
            },
            clear=False,
        ):
            result = p.plan("帮我研究一个 AI 产品并生成报告")
    assert result.method == "heuristic"
    assert len(result.plan.nodes) == 1
    assert result.plan.nodes[0].skill == "claude-code"
