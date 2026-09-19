"""Report Agent — A2A-compatible FastAPI server."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
app = FastAPI(title="AOP Report Agent", version="0.2.0")
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


def _extract_query(params: dict[str, Any]) -> str:
    message = params.get("message") or {}
    parts = message.get("parts") or []
    texts = [p.get("text", "").strip() for p in parts if p.get("type") == "text" and p.get("text")]
    if texts:
        return " ".join(texts).strip()
    raise ValueError("message.parts must include at least one text part")


def run_report(query: str) -> dict[str, Any]:
    markdown = "\n".join(
        [
            f"# Report: {query}",
            "",
            f"_Generated at {_utc_now()}_",
            "",
            "## Executive Summary",
            f"This report aggregates upstream research and knowledge retrieval for **{query}**.",
            "",
            "## Key Findings",
            "1. **Agent Registry** enables skill discovery and online routing.",
            "2. **Planner** produces an executable Task DAG from natural-language goals.",
            "3. **Router + Scheduler** select online agents and run ready nodes in parallel.",
            "4. **Artifacts** land in object storage for Console preview and reuse.",
            "",
            "## Architecture Snapshot",
            "",
            "```",
            "User Goal → Planner → Task DAG → Router → A2A Agents → Aggregator → Report",
            "```",
            "",
            "## Recommendations",
            "- Keep critical agents (search / rag / analysis / report) online before large runs.",
            "- Use Workflow templates for repeatable research pipelines.",
            "- Enable `AUTH_REQUIRED` in non-local environments.",
            "",
            "## Appendix",
            f"- Input goal length: {len(query)} chars",
            "- Format: markdown",
            "",
        ]
    )
    return {"query": query, "format": "markdown", "content": markdown}


def _completed_task(task_id: str, query: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "report-markdown",
                "description": "Markdown report",
                "parts": [{"type": "text", "text": payload["content"]}],
            },
            {
                "artifactId": str(uuid.uuid4()),
                "name": "report-meta",
                "description": "Report metadata",
                "parts": [{"type": "data", "data": payload}],
            },
        ],
        "metadata": {"skillId": "report-generation", "query": query},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": "report-agent"}


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
            payload = run_report(query)
            result = _completed_task(str(uuid.uuid4()), query, payload)
            
            # P36.1: Cache result for idempotency
            if idempotency_key:
                _IDEMPOTENCY_CACHE[idempotency_key] = result
            
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

    port = int(os.getenv("PORT", "8003"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
