"""Stub PPT builds slides from upstream research, not Point A/B/C demos."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from stub_pptx import _slides_from_query, _topic_from_goal, build_stub_pptx  # noqa: E402


def test_topic_from_goal_prefers_ui2v():
    assert _topic_from_goal("搜索ui2v的相关内容，生成一份功能介绍的演示 PPT") == "ui2v"


def test_slides_use_upstream_findings():
    query = """User goal: 搜索ui2v的相关内容，生成一份功能介绍的演示 PPT
Current node: ppt
Upstream results (via handoff):

### search (web-search) (confidence=0.85)
handoff: Completed web-search; unlock ppt
Search results for: ui2v
Source: bing

1. UI2V official overview
   https://example.com/ui2v
   UI2V turns UI mockups into short product videos with one click.

2. UI2V feature list
   https://example.com/ui2v/features
   Supports timeline edit, brand kit, and batch export.

Please continue based on the upstream results.
"""
    slides = _slides_from_query(query)
    titles = [t for t, _ in slides]
    assert any("ui2v" in t.lower() for t in titles)
    flat = " ".join(b for _, bullets in slides for b in bullets)
    assert "UI mockups" in flat or "timeline" in flat or "UI2V" in flat
    assert "Point A" not in flat
    assert "agentic PPT" not in flat


def test_build_stub_pptx_bytes():
    raw, meta = build_stub_pptx("User goal: ui2v features\n")
    assert raw[:2] == b"PK"  # zip/pptx
    assert meta["source"] == "stub"
    assert meta.get("topic") == "ui2v"
