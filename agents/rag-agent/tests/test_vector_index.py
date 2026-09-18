"""Unit tests for RAG TF-IDF index (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vector_index import TfidfIndex, tokenize  # noqa: E402


def test_tokenize_cjk_and_latin():
    toks = set(tokenize("AOP 调度平台 DAG scheduling"))
    assert "aop" in toks
    assert "scheduling" in toks
    assert "调度" in toks or "平台" in toks


def test_vector_ranks_relevant_doc_first():
    docs = [
        {
            "doc_id": "1",
            "title": "Cooking pasta",
            "tags": ["food"],
            "content": "Boil water and add spaghetti noodles with salt.",
        },
        {
            "doc_id": "2",
            "title": "Task DAG Scheduling",
            "tags": ["dag", "scheduler"],
            "content": "The Planner turns a user goal into a Task DAG. Ready nodes enqueue to Redis Streams.",
        },
        {
            "doc_id": "3",
            "title": "Garden tips",
            "tags": ["plants"],
            "content": "Water tomatoes in the morning and prune leaves.",
        },
    ]
    idx = TfidfIndex()
    idx.fit(docs)
    hits = idx.search("How does Task DAG scheduling work with Redis?", top_k=2)
    assert hits
    assert hits[0].doc["doc_id"] == "2"
    assert hits[0].score > hits[-1].score or len(hits) == 1
