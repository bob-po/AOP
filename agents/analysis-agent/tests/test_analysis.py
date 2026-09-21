"""Analysis agent tests — deterministic path only (no network / no LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# analysis-agent and report-agent both expose a top-level `agent`/`context`
# module; drop any cached copy so a root-level pytest run resolves the right one.
for _m in ("agent", "context"):
    sys.modules.pop(_m, None)

from agent import parse_composed_query, run_analysis  # noqa: E402


COMPOSED = (
    "User goal: 分析多智能体编排平台的市场机会\n"
    "\n"
    "Upstream results:\n"
    "### search (web-search)\n"
    "https://example.com/a\n"
    "https://example.com/b\n"
    "### rag (rag-retrieval)\n"
    "AOP 平台将用户目标转换为 Task DAG 并调度执行。\n"
)


def test_parse_composed_query_goal_and_upstream():
    parsed = parse_composed_query(COMPOSED)
    assert parsed["goal"] == "分析多智能体编排平台的市场机会"
    assert set(parsed["upstream"]) == {"search", "rag"}
    assert "example.com/a" in parsed["upstream"]["search"]


def test_parse_composed_query_bare_goal():
    parsed = parse_composed_query("just a plain goal")
    assert parsed["goal"] == "just a plain goal"
    assert parsed["upstream"] == {}


def test_run_analysis_deterministic_is_input_driven(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = run_analysis(COMPOSED)
    assert payload["query"] == "分析多智能体编排平台的市场机会"
    assert "多智能体编排平台" in payload["summary"]
    assert isinstance(payload["insights"], list)
    assert any("example.com" in i.get("detail", "") for i in payload["insights"])
