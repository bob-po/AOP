"""Report agent tests — deterministic path only (no network / no LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# analysis-agent and report-agent both expose a top-level `agent`/`context`
# module; drop any cached copy so a root-level pytest run resolves the right one.
for _m in ("agent", "context"):
    sys.modules.pop(_m, None)

from agent import parse_composed_query, run_report  # noqa: E402


COMPOSED = (
    "User goal: 分析多智能体编排平台的市场机会\n"
    "\n"
    "Upstream results:\n"
    "### search (web-search)\n"
    "https://example.com/a\n"
    "### analysis (business-analysis)\n"
    "summary: 市场机会集中在 Task DAG 编排能力。\n"
)


def test_parse_composed_query_goal_and_upstream():
    parsed = parse_composed_query(COMPOSED)
    assert parsed["goal"] == "分析多智能体编排平台的市场机会"
    assert set(parsed["upstream"]) == {"search", "analysis"}


def test_run_report_deterministic_is_input_driven(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = run_report(COMPOSED)
    assert payload["format"] == "markdown"
    assert payload["query"] == "分析多智能体编排平台的市场机会"
    content = payload["content"]
    assert "分析多智能体编排平台的市场机会" in content
    assert "Research Findings (Web Search)" in content
    assert "example.com" in content
    assert "Business Analysis" in content
