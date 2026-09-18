"""Phase 19: planner JSON repair + goal decomposition."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from planner import Planner
from planner.dag import PlanNode, TaskPlan, validate_plan
from planner.decompose import decompose_to_nodes, split_goal_fragments
from planner.json_plan import extract_json_object, nodes_from_payload


SKILLS = {
    "web-search",
    "knowledge-search",
    "business-analysis",
    "report-generation",
    "text-to-image",
    "text-to-video",
}


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
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=sorted(SKILLS)):
        with patch.dict(os.environ, {"PLANNER_V2": "1", "HITL_SKILLS": "report-generation"}):
            result = p.plan("1. 搜索资料 2. 分析一下 3. 生成报告")
    assert result.method == "heuristic_steps"
    assert len(result.plan.nodes) >= 3


def test_planner_llm_invalid_falls_back_to_heuristic():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=sorted(SKILLS)):
        with patch.dict(os.environ, {"PLANNER_LLM": "true", "PLANNER_V2": "0", "HITL_SKILLS": "off"}):
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
    assert {n.skill for n in result.plan.nodes} <= SKILLS


def test_research_goal_still_heuristic_pipeline():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=sorted(SKILLS)):
        with patch.dict(os.environ, {"PLANNER_V2": "1", "HITL_SKILLS": "report-generation"}):
            result = p.plan("帮我研究一个 AI 产品并生成报告")
    assert result.method == "heuristic"
    ids = {n.id for n in result.plan.nodes}
    assert {"search", "rag", "analysis", "report"} <= ids
