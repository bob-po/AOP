"""Report agent tests — deterministic path only (no network / no LLM)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _m in list(sys.modules):
    if _m == "agent" or _m == "context" or _m.startswith("pipeline"):
        sys.modules.pop(_m, None)

from agent import parse_composed_query, run_report  # noqa: E402
from pipeline.sandbox import sanitize_markup  # noqa: E402


COMPOSED = (
    "User goal: 分析多智能体编排平台的市场机会\n"
    "\n"
    "Upstream results:\n"
    "### search (web-search)\n"
    "https://example.com/a\n<script>alert(1)</script>\n"
    "### analysis (business-analysis)\n"
    "summary: 市场机会集中在 Task DAG 编排能力。\n"
)

EXPERIMENT = (
    "User goal: 比较两种图像重建方法\n"
    "\n"
    "Upstream results:\n"
    "### results (analysis)\n"
    "Baseline PSNR 28.1\nOurs PSNR 31.4\nSSIM 0.91\nLPIPS 0.12\n"
)


def test_parse_composed_query_goal_and_upstream():
    parsed = parse_composed_query(COMPOSED)
    assert parsed["goal"] == "分析多智能体编排平台的市场机会"
    assert set(parsed["upstream"]) == {"search", "analysis"}


def test_run_report_emits_html_bundle(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("REPORT_PDF_ENGINE", "none")
    payload = run_report(COMPOSED)
    assert payload["format"] == "html"
    assert payload["query"] == "分析多智能体编排平台的市场机会"
    html_doc = payload["files"]["report.html"]
    assert "分析多智能体编排平台的市场机会" in html_doc
    body = html_doc.split("</h1>", 1)[-1]
    assert "分析多智能体编排平台的市场机会" not in body
    assert "<style" in html_doc
    assert "没有可绘制" not in html_doc
    assert "example.com/a" in html_doc
    assert "Task DAG" in html_doc
    assert "<script" not in html_doc.lower()
    assert "report.css" in payload["files"]
    assert "assets/diagrams/outline.svg" in payload["files"]
    assert payload["sandbox"]["markup"] == "escaped+stripped"
    assert payload["pdf"]["engine"] == "none"
    assert "1. 摘要" in payload["content"]
    numbers = [section["title"] for section in payload["plan"]["sections"]]
    assert numbers[:3] == ["摘要", "背景", "研究发现"]


def test_experiment_plan_includes_metric_sections(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("REPORT_PDF_ENGINE", "none")
    payload = run_report(EXPERIMENT)
    titles = []

    def walk(sections):
        for section in sections:
            titles.append(f"{section['number']} {section['title']}")
            walk(section.get("children") or [])

    walk(payload["plan"]["sections"])
    assert "4 实验结果" in titles
    assert "4.1 PSNR" in titles
    assert "4.2 SSIM" in titles
    assert "4.3 LPIPS" in titles
    assert "4.4 对比图" in titles
    assert "7 References" in titles
    assert "31.4" in payload["files"]["assets/charts/psnr.svg"]


def test_sanitize_strips_active_markup():
    cleaned = sanitize_markup("<p onclick='x()'>ok</p><script>bad()</script><a href='javascript:alert(1)'>x</a>")
    assert "<script" not in cleaned.lower()
    assert "onclick" not in cleaned.lower()
    assert "javascript:" not in cleaned.lower()
    assert "ok" in cleaned
