"""Tests for Chinese→English query variants and Bing relevance gate."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from search import _results_relevant, search_query_variants  # noqa: E402


def test_variants_prefer_english_for_cjk_tech_query():
    variants = search_query_variants("用一句话介绍 A2A 协议是什么")
    assert variants
    assert any("Agent2Agent" in v for v in variants)
    assert any("A2A" in v for v in variants)


def test_reject_dictionary_junk_for_a2a_query():
    junk = [
        {
            "title": "用 （汉语汉字）_百度百科",
            "url": "https://baike.baidu.com/item/%E7%94%A8/5342956",
            "snippet": "用（拼音：yòng），是汉语通用规范一级字。",
        }
    ]
    assert not _results_relevant("用一句话介绍 A2A 协议是什么", junk)


def test_reject_italian_utility_a2a():
    junk = [
        {
            "title": "A2A",
            "url": "https://en.wikipedia.org/wiki/A2A",
            "snippet": "Italian utilities company A2A S.p.A.",
        }
    ]
    assert not _results_relevant("用一句话介绍 A2A 协议是什么", junk)


def test_accept_a2a_protocol_hits():
    good = [
        {
            "title": "A2A Protocol",
            "url": "https://a2a-protocol.org/",
            "snippet": "Agent2Agent open protocol",
        }
    ]
    assert _results_relevant("用一句话介绍 A2A 协议是什么", good)
