"""Analysis Agent — business-analysis skill for AOP Planner pipeline."""

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
    extract_urls,
    format_upstream,
    llm_available,
    llm_chat,
    parse_composed_query,
    parse_json_lenient,
)
try:
    from context_enhanced import (
        llm_analysis_with_metadata,
        get_llm_provider,
    )
    ENHANCED_CONTEXT_AVAILABLE = True
except ImportError:
    ENHANCED_CONTEXT_AVAILABLE = False

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
app = FastAPI(title="AOP Analysis Agent", version="0.1.0")
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


def _llm_analysis(goal: str, upstream: dict[str, Any]) -> dict[str, Any] | None:
    """Synthesize insights via an OpenAI-compatible LLM; None on any failure."""
    
    # P37.2: Use enhanced context with metadata if available (default to enhanced)
    use_enhanced = os.getenv("ANALYSIS_USE_ENHANCED", "true").lower() == "true"
    
    if use_enhanced and ENHANCED_CONTEXT_AVAILABLE:
        result = llm_analysis_with_metadata(goal, upstream)
        if result:
            # Extract metadata and store it separately
            metadata = result.pop("metadata", {})
            print(f"[Analysis Agent] Enhanced analysis completed: {metadata.get('tokens_used', 0)} tokens, {metadata.get('latency_ms', 0)}ms")
            return result
    
    # Fallback to legacy implementation
    system = (
        "You are a business analyst for a multi-agent AI orchestration platform. "
        "Analyze the provided research context (web search results and knowledge-base "
        "retrieval) and produce concise, specific, evidence-grounded insights. "
        "Respond in the same language as the goal. Return ONLY a JSON object with keys "
        '"summary" (string) and "insights" (array of {"theme", "detail"} objects).'
    )
    user = f"Goal: {goal}"
    if upstream:
        user += f"\n\nUpstream results:\n{format_upstream(upstream)}"

    raw = llm_chat(system, user, json_mode=True)
    if not raw:
        return None
    data = parse_json_lenient(raw)
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary") or "").strip()
    insights = data.get("insights")
    if not summary or not isinstance(insights, list) or not insights:
        return None
    return {"summary": summary, "insights": insights}


def _deterministic_analysis(goal: str, upstream: dict[str, Any]) -> dict[str, Any]:
    """Input-driven fallback when no LLM is configured."""
    search_text = upstream.get("search", "")
    rag_text = upstream.get("rag", "")
    urls = extract_urls(search_text)

    insights: list[dict[str, str]] = []
    if search_text:
        refs = ", ".join(urls[:3]) or "no direct URLs extracted"
        insights.append(
            {
                "theme": "Market signal (web search)",
                "detail": f"{len(urls)} source(s) surfaced for this goal; top references: {refs}.",
            }
        )
    if rag_text:
        snippet = rag_text[:180] + ("..." if len(rag_text) > 180 else "")
        insights.append({"theme": "Knowledge base", "detail": f"Internal corpus: {snippet}"})
    insights.append(
        {
            "theme": "Recommendation",
            "detail": (
                "Cross-reference external search signals with internal knowledge "
                "to validate positioning and close capability gaps."
            ),
        }
    )

    summary = (
        f"Analysis of '{goal}' synthesized from {len(urls)} web source(s) and "
        f"{'internal knowledge' if rag_text else 'no knowledge-base hit'}."
    )
    return {"query": goal, "summary": summary, "insights": insights}


def run_analysis(query: str) -> dict[str, Any]:
    parsed = parse_composed_query(query)
    goal = parsed["goal"]
    upstream = parsed["upstream"]

    if llm_available():
        llm = _llm_analysis(goal, upstream)
        if llm:
            return {"query": goal, **llm}

    return _deterministic_analysis(goal, upstream)


def _completed_task(task_id: str, query: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "analysis-summary",
                "parts": [{"type": "text", "text": payload["summary"]}],
            },
            {
                "artifactId": str(uuid.uuid4()),
                "name": "analysis-insights",
                "parts": [{"type": "data", "data": payload}],
            },
        ],
        "metadata": {"skillId": "business-analysis", "query": query},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": "analysis-agent"}


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
            payload = run_analysis(query)
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

    port = int(os.getenv("PORT", "8004"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
