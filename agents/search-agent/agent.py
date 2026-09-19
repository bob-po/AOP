"""Search Agent — A2A-compatible FastAPI server (Phase 16 multi-backend)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from search import run_search

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"

app = FastAPI(title="AOP Search Agent", version="0.2.0")
_TASKS: dict[str, dict[str, Any]] = {}

# P36.1: In-memory idempotency cache for Agent-side deduplication
_IDEMPOTENCY_CACHE: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_card() -> dict[str, Any]:
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    override = os.getenv("AGENT_URL")
    if override:
        card["url"] = override if override.endswith("/") else f"{override}/"
    return card


def _text_part(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _data_part(data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "data", "data": data}


def _extract_query(params: dict[str, Any]) -> str:
    message = params.get("message") or {}
    parts = message.get("parts") or []
    texts = [p.get("text", "").strip() for p in parts if p.get("type") == "text" and p.get("text")]
    if texts:
        return " ".join(texts).strip()
    raise ValueError("message.parts must include at least one text part")


def _completed_task(task_id: str, query: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {
            "state": "completed",
            "timestamp": _utc_now(),
        },
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "search-summary",
                "description": "Human-readable search summary",
                "parts": [_text_part(payload["summary"])],
            },
            {
                "artifactId": str(uuid.uuid4()),
                "name": "search-results",
                "description": "Structured search results",
                "parts": [
                    _data_part(
                        {
                            "query": payload["query"],
                            "source": payload["source"],
                            "tried": payload.get("tried") or [],
                            "results": payload["results"],
                        }
                    )
                ],
            },
        ],
        "metadata": {"skillId": "web-search", "query": query, "source": payload.get("source")},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "agent": "search-agent",
        "version": "0.2.0",
        "search_mode": os.getenv("SEARCH_MODE", "auto"),
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
            # P36.1: Extract idempotency key if present
            idempotency_key = params.get("idempotencyKey") or params.get("idempotency_key")
            
            # P36.1: Check if request already processed (Agent-side idempotency)
            if idempotency_key and idempotency_key in _IDEMPOTENCY_CACHE:
                cached = _IDEMPOTENCY_CACHE[idempotency_key]
                return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": cached})
            
            query = _extract_query(params)
            payload = await run_search(query)
            task_id = str(uuid.uuid4())
            result = _completed_task(task_id, query, payload)
            
            # P36.1: Cache result for idempotency
            if idempotency_key:
                _IDEMPOTENCY_CACHE[idempotency_key] = result
            
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})

        if method == "tasks/get":
            task_id = params.get("id")
            task = _TASKS.get(task_id)
            if not task:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32001, "message": f"Task not found: {task_id}"},
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

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
