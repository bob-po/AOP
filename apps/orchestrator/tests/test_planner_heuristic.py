"""Planner heuristic tests (no database)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from planner import Planner
from planner.dag import DAGValidationError
from planner.decompose import decompose_to_nodes, split_goal_fragments


SKILLS = {
    "web-search",
    "knowledge-search",
    "business-analysis",
    "report-generation",
    "ppt-generation",
    "text-to-image",
    "text-to-video",
}


@pytest.fixture
def planner() -> Planner:
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=sorted(SKILLS)):
        yield p


def _plan(planner: Planner, goal: str, *, hitl: str = "report-generation,ppt-generation"):
    with patch.object(planner, "list_available_skills", return_value=sorted(SKILLS)):
        with patch.dict(os.environ, {"HITL_SKILLS": hitl, "PLANNER_V2": "1"}, clear=False):
            return planner.plan(goal)


def test_research_goal_builds_pipeline(planner: Planner):
    result = _plan(planner, "帮我研究一个 AI 产品并生成报告", hitl="report-generation")
    assert result.method in {"heuristic", "heuristic_steps"}
    ids = {n.id for n in result.plan.nodes}
    assert {"search", "rag", "analysis", "report"} <= ids
    report = next(n for n in result.plan.nodes if n.id == "report")
    assert report.requires_approval is True
    assert "analysis" in report.depends_on


def test_simple_qa_is_search_only(planner: Planner):
    result = _plan(planner, "用一句话介绍 A2A 协议是什么")
    assert result.method == "heuristic"
    skills = [n.skill for n in result.plan.nodes]
    assert skills == ["web-search"]
    assert {n.id for n in result.plan.nodes} == {"search"}


def test_deep_research_without_report_skips_report(planner: Planner):
    result = _plan(
        planner,
        "帮我深入了解多智能体编排平台的架构设计与关键取舍以及落地实践经验",
    )
    ids = {n.id for n in result.plan.nodes}
    assert {"search", "rag", "analysis"} <= ids
    assert "report" not in ids
    assert "ppt" not in ids


def test_image_request_adds_media_node(planner: Planner):
    result = _plan(planner, "生成一张宣传海报", hitl="off")
    ids = {n.id for n in result.plan.nodes}
    assert ids == {"image"}


def test_search_then_intro_ppt_is_lean(planner: Planner):
    """User complaint case: 搜索什么是X，生成介绍 PPT → search → ppt only."""
    goal = "搜索什么是jev，生成一份介绍 PPT"
    assert split_goal_fragments(goal) == ["搜索什么是jev", "生成一份介绍 PPT"]
    result = _plan(planner, goal)
    skills = [n.skill for n in result.plan.nodes]
    ids = {n.id for n in result.plan.nodes}
    assert "ppt-generation" in skills
    assert "web-search" in skills
    assert "knowledge-search" not in skills
    assert "business-analysis" not in skills
    assert "report-generation" not in skills
    assert ids == {"search", "ppt"}
    ppt = next(n for n in result.plan.nodes if n.id == "ppt")
    assert ppt.depends_on == ["search"]
    assert ppt.requires_approval is True


def test_ppt_without_comma_still_lean(planner: Planner):
    result = _plan(planner, "搜索资料后生成一份产品发布会 PPT")
    skills = {n.skill for n in result.plan.nodes}
    assert skills == {"web-search", "ppt-generation"}
    ppt = next(n for n in result.plan.nodes if n.id == "ppt")
    assert ppt.depends_on == ["search"]


def test_ppt_only_still_searches_for_context(planner: Planner):
    result = _plan(planner, "生成一份介绍 A2A 的 PPT", hitl="off")
    skills = {n.skill for n in result.plan.nodes}
    assert skills == {"web-search", "ppt-generation"}


def test_ppt_and_report_both_when_asked(planner: Planner):
    result = _plan(planner, "调研竞品并生成报告和 PPT", hitl="off")
    ids = {n.id for n in result.plan.nodes}
    assert "report" in ids
    assert "ppt" in ids
    assert "analysis" in ids


def test_search_only_goal(planner: Planner):
    result = _plan(planner, "搜索 OpenAI 最新消息", hitl="off")
    assert {n.skill for n in result.plan.nodes} == {"web-search"}


def test_rag_explicit(planner: Planner):
    result = _plan(planner, "在知识库里查 A2A 并生成报告", hitl="off")
    skills = {n.skill for n in result.plan.nodes}
    assert "knowledge-search" in skills
    assert "report-generation" in skills


def test_decompose_comma_steps():
    nodes = decompose_to_nodes(
        "搜索什么是jev，生成一份介绍 PPT",
        SKILLS,
        hitl={"ppt-generation"},
    )
    assert [(n.id, n.skill, n.depends_on) for n in nodes] == [
        ("search", "web-search", []),
        ("ppt", "ppt-generation", ["search"]),
    ]


def test_empty_goal_raises():
    p = Planner(database_url="postgresql://invalid/invalid")
    with pytest.raises(ValueError, match="goal is required"):
        p.plan("   ")


def test_no_skills_raises():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=[]):
        with pytest.raises(ValueError, match="no online agents"):
            p.plan("anything")


def test_fallback_single_skill():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=["web-search"]):
        with patch.object(p, "_heuristic_nodes", return_value=[]):
            result = p.plan("noop")
    assert result.method == "fallback"
    assert len(result.plan.nodes) == 1
    assert result.plan.nodes[0].skill == "web-search"


def test_llm_disabled_by_default(planner: Planner):
    with patch.object(planner, "list_available_skills", return_value=sorted(SKILLS)):
        with patch.dict(os.environ, {"PLANNER_LLM": "false"}, clear=False):
            with patch.object(planner, "_try_llm_nodes") as llm:
                result = planner.plan("搜索资料")
                llm.assert_not_called()
    assert result.method == "heuristic"


def test_plan_rejects_when_validate_fails():
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=["web-search"]):
        from planner.dag import PlanNode

        bad = [PlanNode(id="a", skill="missing-skill")]
        with patch.object(p, "_heuristic_nodes", return_value=bad):
            with pytest.raises(DAGValidationError):
                p.plan("x")
