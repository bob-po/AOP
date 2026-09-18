#!/usr/bin/env python3
"""Phase 16 smoke: Search (mock) + RAG vector ranking."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SEARCH = ROOT / "agents" / "search-agent"
RAG = ROOT / "agents" / "rag-agent"


def run_pytest(cwd: Path, pattern: str) -> int:
    cmd = [sys.executable, "-m", "pytest", "-q", str(cwd / "tests"), "-k", pattern]
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=str(cwd))


def main() -> int:
    print("[1/3] Search mock unit tests")
    os.environ["SEARCH_MODE"] = "mock"
    if run_pytest(SEARCH, "mock") != 0:
        return 1

    print("[2/3] RAG vector unit tests")
    if run_pytest(RAG, "vector") != 0:
        return 1

    print("[3/3] Live RAG ranking demo (in-process)")
    sys.path.insert(0, str(RAG))
    from vector_index import TfidfIndex
    import json

    docs = json.loads((RAG / "knowledge" / "corpus.json").read_text(encoding="utf-8"))["documents"]
    idx = TfidfIndex()
    idx.fit(docs)
    hits = idx.search("Redis Pub/Sub WebSocket realtime trace", top_k=3)
    assert hits, "expected corpus hits"
    print("  top:", hits[0].doc.get("doc_id"), hits[0].doc.get("title"), f"score={hits[0].score:.3f}")

    sys.path.insert(0, str(SEARCH))
    from search import run_search

    payload = asyncio.run(run_search("A2A agent orchestration"))
    print("  search source:", payload["source"], "n=", len(payload["results"]))

    print("PHASE16 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
