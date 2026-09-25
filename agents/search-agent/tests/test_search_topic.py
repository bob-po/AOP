"""Search topic extraction + relevance / junk filters."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from search import (  # noqa: E402
    _is_serp_junk,
    _results_relevant,
    extract_search_topic,
    filter_relevant_results,
    run_search,
    search_query_variants,
)


def test_extract_topic_ui2v_from_chinese_goal():
    goal = "搜索ui2v的相关内容，生成一份功能介绍的演示 PPT"
    assert extract_search_topic(goal) == "ui2v"


def test_extract_topic_bilibili_from_chinese_goal():
    goal = "帮我调研一下哔哩哔哩，搜索资料，输出ppt"
    assert extract_search_topic(goal) == "哔哩哔哩"
    variants = search_query_variants(goal)
    assert any("bilibili" in v.lower() for v in variants)
    assert variants[0] == "哔哩哔哩" or "哔哩哔哩" in variants[0]


def test_reject_dictionary_pages_for_bilibili():
    junk = [
        {
            "title": "《帮》的拼音, 帮字的意思、组词",
            "url": "https://www.hgcha.com/zidian/5d11e9dd.html",
            "snippet": "帮助 英 help",
        }
    ]
    assert _is_serp_junk(junk[0])
    assert filter_relevant_results("哔哩哔哩", junk) == []
    assert not _results_relevant("帮我调研一下哔哩哔哩，搜索资料，输出ppt", junk)


def test_tech_token_adjacent_to_cjk():
    variants = search_query_variants("搜索ui2v的相关内容，生成一份功能介绍的演示 PPT")
    assert any("ui2v" in v.lower() for v in variants)
    assert variants[0].lower().startswith("ui2v") or "ui2v" in variants[0].lower()


def test_reject_search_engine_homepages():
    junk = [
        {"title": "搜狗", "url": "https://www.sogou.com/", "snippet": "搜索"},
        {"title": "必应", "url": "https://cn.bing.com/", "snippet": "Microsoft"},
        {"title": "360", "url": "https://www.so.com/", "snippet": "搜索"},
        {"title": "Google", "url": "https://www.google.com.hk/?hl=zh-cn", "snippet": "Google"},
        {"title": "一搜", "url": "https://www.17so.cn/", "snippet": "聚合"},
    ]
    assert all(_is_serp_junk(r) for r in junk)
    assert not _results_relevant("搜索ui2v的相关内容，生成一份功能介绍的演示 PPT", junk)
    assert filter_relevant_results("ui2v", junk) == []


def test_relevant_when_topic_present():
    rows = [
        {
            "title": "UI2V: UI to Video generation",
            "url": "https://example.com/ui2v",
            "snippet": "UI2V converts UI designs into videos.",
        },
        {
            "title": "ui2v features",
            "url": "https://docs.example.com/ui2v/features",
            "snippet": "Feature overview of ui2v.",
        },
        {
            "title": "unrelated",
            "url": "https://example.com/other",
            "snippet": "nothing here",
        },
    ]
    assert _results_relevant("搜索ui2v的相关内容", rows)
    kept = filter_relevant_results("ui2v", rows)
    assert all("ui2v" in (r["title"] + r["url"] + r["snippet"]).lower() for r in kept)


def test_run_search_no_relevant_when_backends_junk(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "live")
    monkeypatch.setenv("SEARCH_ALLOW_MOCK_FALLBACK", "false")
    monkeypatch.setenv("SEARCH_FETCH_PAGES", "0")
    monkeypatch.delenv("DEERFLOW_URL", raising=False)

    junk = [
        {"title": "搜狗", "url": "https://www.sogou.com/", "snippet": "搜索"},
        {"title": "必应", "url": "https://cn.bing.com/", "snippet": "Microsoft"},
    ]

    async def _junk(_q, *, limit=5):
        return list(junk)

    monkeypatch.setattr("search.wikipedia_opensearch", _junk)
    monkeypatch.setattr("search.bing_search", _junk)
    monkeypatch.setattr("search.duckduckgo_instant", AsyncMock(return_value=None))
    monkeypatch.setattr("search.duckduckgo_lite", AsyncMock(return_value=None))

    payload = asyncio.run(run_search("搜索ui2v的相关内容，生成一份功能介绍的演示 PPT"))
    assert payload["status"] == "no_relevant_results"
    assert payload["results"] == []
    assert payload["confidence"] == 0.0
    assert payload["query"] == "ui2v"
    assert payload["tried"]
