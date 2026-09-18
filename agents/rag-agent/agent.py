"""RAG Agent — A2A FastAPI with hybrid TF-IDF vector retrieval (Phase 16)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vector_index import TfidfIndex

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
CORPUS_PATH = ROOT / "knowledge" / "corpus.json"

app = FastAPI(title="AOP RAG Agent", version="0.3.0")
_TASKS: dict[str, dict[str, Any]] = {}
_CORPUS: list[dict[str, Any]] | None = None
_INDEX: TfidfIndex | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_card() -> dict[str, Any]:
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    override = os.getenv("AGENT_URL")
    if override:
        card["url"] = override if override.endswith("/") else f"{override}/"
    return card


def load_corpus() -> list[dict[str, Any]]:
    global _CORPUS
    if _CORPUS is not None:
        return _CORPUS
    if CORPUS_PATH.exists():
        data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        _CORPUS = list(data.get("documents") or [])
    else:
        _CORPUS = []
    return _CORPUS


def get_index() -> TfidfIndex:
    global _INDEX
    if _INDEX is None:
        idx = TfidfIndex()
        idx.fit(load_corpus())
        _INDEX = idx
    return _INDEX


def _extract_query(params: dict[str, Any]) -> str:
    message = params.get("message") or {}
    parts = message.get("parts") or []
    texts = [p.get("text", "").strip() for p in parts if p.get("type") == "text" and p.get("text")]
    if texts:
        return " ".join(texts).strip()
    raise ValueError("message.parts must include at least one text part")


def run_rag(query: str, *, top_k: int | None = None) -> dict[str, Any]:
    top_k = top_k or int(os.getenv("RAG_TOP_K") or "3")
    alpha = float(os.getenv("RAG_HYBRID_ALPHA") or "0.65")
    index = get_index()
    scored = index.search(query, top_k=top_k, hybrid_alpha=alpha)
    docs = load_corpus()

    if not scored and docs:
        scored = []  # empty

    citations = []
    for item in scored:
        d = item.doc
        citations.append(
            {
                "doc_id": d.get("doc_id"),
                "title": d.get("title"),
                "snippet": (d.get("content") or "")[:280],
                "tags": d.get("tags") or [],
                "score": round(item.score, 4),
                "vector_score": round(item.vector_score, 4),
                "keyword_score": round(item.keyword_score, 4),
            }
        )

    method = "hybrid-tfidf"
    if not citations and docs:
        # Soft fallback: first docs (should be rare with hybrid)
        for d in docs[: min(2, len(docs))]:
            citations.append(
                {
                    "doc_id": d.get("doc_id"),
                    "title": d.get("title"),
                    "snippet": (d.get("content") or "")[:280],
                    "tags": d.get("tags") or [],
                    "score": 0.0,
                    "vector_score": 0.0,
                    "keyword_score": 0.0,
                }
            )
        method = "corpus-fallback"

    if citations:
        joined = " ".join(c["snippet"] for c in citations)
        answer = (
            f"Based on the knowledge base (method={method}) for '{query}': {joined}"
        )
    else:
        answer = (
            f"No corpus hit for '{query}'. Ensure agents/rag-agent/knowledge/corpus.json is present."
        )

    return {
        "query": query,
        "answer": answer,
        "citations": citations,
        "corpus_size": len(docs),
        "method": method,
        "hybrid_alpha": alpha,
    }


def _completed_task(task_id: str, query: str, payload: dict[str, Any], skill: str) -> dict[str, Any]:
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "rag-answer",
                "description": "Knowledge answer",
                "parts": [{"type": "text", "text": payload["answer"]}],
            },
            {
                "artifactId": str(uuid.uuid4()),
                "name": "rag-citations",
                "description": "Structured citations with vector scores",
                "parts": [{"type": "data", "data": payload}],
            },
        ],
        "metadata": {
            "skillId": skill,
            "query": query,
            "method": payload.get("method"),
        },
    }
    _TASKS[task_id] = task
    return task


@app.on_event("startup")
async def _warmup() -> None:
    get_index()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent": "rag-agent",
        "version": "0.3.0",
        "corpus": len(load_corpus()),
        "index": "tfidf-hybrid",
    }


@app.get("/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    return JSONResponse(load_card(), media_type="application/json")


@app.post("/")
@app.post("/a2a")
async def a2a_rpc(request: Request) -> JSONResponse:
    body = await request.json()
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    try:
        if method == "message/send":
            query = _extract_query(params)
            meta = params.get("metadata") or {}
            skill = str(meta.get("skillId") or "knowledge-search")
            payload = run_rag(query)
            result = _completed_task(str(uuid.uuid4()), query, payload, skill)
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})
        if method == "tasks/get":
            task = _TASKS.get(params.get("id"))
            if not task:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32001, "message": "Task not found"},
                    }
                )
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": task})
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )
    except ValueError as exc:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": str(exc)},
            }
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8002"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
