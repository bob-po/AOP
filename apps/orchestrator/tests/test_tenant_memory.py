"""Unit tests for tenant memory TF-IDF ranking (no DB)."""

from __future__ import annotations

from memory.tfidf import rank_documents, tokenize


def test_tokenize_cjk_and_latin():
    toks = tokenize("AI 产品报告 product report")
    assert "ai" in toks or "product" in toks
    assert any("产" in t or "报告" in t or "报" in t for t in toks)


def test_rank_prefers_relevant_doc():
    docs = [
        {"title": "weather", "content": "rain and clouds tomorrow", "memory_key": "a"},
        {
            "title": "AI product research",
            "content": "competitive analysis of AI agents and orchestration platforms",
            "memory_key": "b",
        },
        {"title": "cooking", "content": "pasta recipe with tomato", "memory_key": "c"},
    ]
    ranked = rank_documents("AI agent orchestration", docs, top_k=2)
    assert ranked
    assert ranked[0][1]["memory_key"] == "b"
    assert ranked[0][0] > 0
