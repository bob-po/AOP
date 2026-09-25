"""Orchestrator quality gate: refuse unlocking dependents on bad search/PPT."""

from __future__ import annotations

from executor.engine import ExecutionEngine


def _engine() -> ExecutionEngine:
    return ExecutionEngine.__new__(ExecutionEngine)


def test_quality_gate_blocks_no_relevant_search():
    eng = _engine()
    gate = eng._quality_gate(
        skill="web-search",
        text="No relevant results for: ui2v",
        data={
            "status": "no_relevant_results",
            "confidence": 0.0,
            "results": [],
            "error": "all backends returned empty or irrelevant SERP hits",
        },
    )
    assert gate["ok"] is False
    assert gate["status"] == "no_relevant_results"
    assert "Search quality gate" in gate["message"]


def test_quality_gate_blocks_serp_junk_heuristic():
    eng = _engine()
    gate = eng._quality_gate(
        skill="web-search",
        text=(
            "1. 搜狗 https://www.sogou.com/\n"
            "2. 必应 https://cn.bing.com/\n"
            "3. 360 https://www.so.com/\n"
        ),
        data={"status": "ok", "results": [{"title": "x", "url": "https://www.sogou.com/"}]},
    )
    assert gate["ok"] is False
    assert gate["status"] == "no_relevant_results"


def test_quality_gate_allows_relevant_search():
    eng = _engine()
    gate = eng._quality_gate(
        skill="web-search",
        text="Search results for: ui2v\n1. UI2V https://example.com/ui2v\n",
        data={
            "status": "ok",
            "confidence": 0.8,
            "results": [
                {
                    "title": "UI2V",
                    "url": "https://example.com/ui2v",
                    "snippet": "UI to video",
                }
            ],
            "source": "bing",
        },
    )
    assert gate["ok"] is True
    assert gate["confidence"] == 0.8


def test_quality_gate_blocks_ppt_without_research():
    eng = _engine()
    gate = eng._quality_gate(
        skill="ppt-generation",
        text="PPT generation blocked",
        data={"status": "insufficient_research", "confidence": 0.0},
    )
    assert gate["ok"] is False
    assert "PPT quality gate" in gate["message"]
