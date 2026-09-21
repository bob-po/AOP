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

from context import (
    format_upstream,
    llm_available,
    llm_chat,
    parse_composed_query,
)
try:
    from context_enhanced import (
        llm_report_with_metadata,
        extract_structured_data,
        get_llm_provider,
    )
    ENHANCED_CONTEXT_AVAILABLE = True
except ImportError:
    ENHANCED_CONTEXT_AVAILABLE = False

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


def _llm_report(goal: str, upstream: dict[str, Any]) -> str | None:
    """Synthesize a markdown report via an OpenAI-compatible LLM."""
    
    # P37.2: Use enhanced context with structured data processing (default to enhanced)
    use_enhanced = os.getenv("REPORT_USE_ENHANCED", "true").lower() == "true"
    
    if use_enhanced and ENHANCED_CONTEXT_AVAILABLE:
        # Extract structured data from upstream for better report generation
        structured_data = extract_structured_data(upstream)
        print(f"[Report Agent] Extracted structured data from {len(structured_data)} upstream nodes")
        
        # Use enhanced report generation
        report = llm_report_with_metadata(goal, upstream)
        if report:
            return report
    
    # Fallback to legacy implementation
    system = (
        "You are a report writer for a multi-agent AI orchestration platform. "
        "Synthesize the provided research context (web search, knowledge-base retrieval, "
        "business analysis) into a clear, well-structured markdown report with these "
        "sections: Executive Summary, Research Findings, Knowledge Base, Business "
        "Analysis, and Recommendations. Ground every claim in the provided upstream "
        "content. Respond in the same language as the goal. Output markdown only."
    )
    user = f"Goal: {goal}"
    if upstream:
        user += f"\n\nUpstream results:\n{format_upstream(upstream)}"
    return llm_chat(system, user, json_mode=False)


def _deterministic_report(goal: str, upstream: dict[str, Any]) -> str:
    """Input-driven fallback when no LLM is configured."""
    lines = [
        f"# Report: {goal}",
        "",
        f"_Generated at {_utc_now()}_",
        "",
        "## Executive Summary",
        f"Automated research synthesis for the goal: **{goal}**",
        "",
    ]
    section_titles = {
        "search": "Research Findings (Web Search)",
        "rag": "Knowledge Base",
        "analysis": "Business Analysis",
    }
    for node_id, title in section_titles.items():
        body = (upstream.get(node_id) or "").strip()
        if not body:
            continue
        lines += [f"## {title}", "", body[:1500], ""]
    lines += [
        "## Recommendations",
        "",
        "Validate external search signals against internal knowledge, then prioritize "
        "the highest-confidence capability gaps identified above.",
        "",
    ]
    return "\n".join(lines)


def run_report(query: str) -> dict[str, Any]:
    parsed = parse_composed_query(query)
    goal = parsed["goal"]
    upstream = parsed["upstream"]

    content: str | None = None
    if llm_available():
        content = _llm_report(goal, upstream)
    if not content:
        content = _deterministic_report(goal, upstream)

    return {"query": goal, "format": "markdown", "content": content}


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
