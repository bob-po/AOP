"""Planner heuristic tests (no database)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from planner import Planner
from planner.dag import DAGValidationError


SKILLS = {
    "web-search",
    "knowledge-search",
    "business-analysis",
    "report-generation",
    "text-to-image",
    "text-to-video",
}


@pytest.fixture
def planner() -> Planner:
    p = Planner(database_url="postgresql://invalid/invalid")
    with patch.object(p, "list_available_skills", return_value=sorted(SKILLS)):
        yield p


def test_research_goal_builds_pipeline(planner: Planner):
    with patch.object(planner, "list_available_skills", return_value=sorted(SKILLS)):
        with patch.dict(os.environ, {"HITL_SKILLS": "report-generation"}):
            result = planner.plan("帮我研究一个 AI 产品并生成报告")
    assert result.method == "heuristic"
    ids = {n.id for n in result.plan.nodes}
    assert {"search", "rag", "analysis", "report"} <= ids
    report = next(n for n in result.plan.nodes if n.id == "report")
    assert report.requires_approval is True
    assert "analysis" in report.depends_on


def test_image_request_adds_media_node(planner: Planner):
    with patch.object(planner, "list_available_skills", return_value=sorted(SKILLS)):
        with patch.dict(os.environ, {"HITL_SKILLS": "off"}):
            result = planner.plan("生成一张宣传海报")
    ids = {n.id for n in result.plan.nodes}
    assert "image" in ids


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
        # Force heuristic to produce nothing by using goal that doesn't trigger media
        # but search is still added by try_add — so method may be heuristic.
        # Use unavailable-only path via empty heuristic: patch _heuristic_nodes.
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
