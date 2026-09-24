"""Search Agent — A2A-compatible FastAPI server (Phase 16 multi-backend)."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from search import run_search
from page_fetch import fetch_url_sync
try:
    from search_enhanced import run_search_sync
    ENHANCED_SEARCH_AVAILABLE = True
except ImportError:
    ENHANCED_SEARCH_AVAILABLE = False

# A2A OS: make this Agent a first-class citizen — Server *and* Client.
# Inbound task lineage + optional autonomous peer delegation + tasks/cancel.
try:
    from agent_runtime.agent_collab import AgentCollaborator
    from agent_runtime.a2a_server import cancel_task as _a2a_cancel
    _COLLAB = AgentCollaborator(agent_id="search-agent")
except ImportError:  # pragma: no cover - agent-runtime not installed
    _COLLAB = None

    def _a2a_cancel(store, tid):
        if tid and tid in store:
            t = store[tid]
            s = t.get("status")
            if isinstance(s, dict):
                s["state"] = "canceled"
            else:
                t["status"] = {"state": "canceled"}
            return True, t
        return False, None

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"

app = FastAPI(title="AOP Search Agent", version="0.5.0")
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


def _skill_id(params: dict[str, Any]) -> str:
    metadata = params.get("metadata") or {}
    return str(metadata.get("skillId") or metadata.get("skill_id") or "web-search")


def _extract_goal(query: str) -> str:
    """Extract the user's research goal from the executor's composed prompt.

    The orchestrator composes ``User goal: …`` + working memory + upstream results
    into a single message; search only needs the bare goal as its query.
    """
    m = re.search(r"^User goal:\s*(.+)$", query, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return query.strip()


def _looks_like_url(text: str) -> bool:
    return bool(re.match(r"^https?://\S+$", (text or "").strip(), flags=re.I))


def _run_url_fetch(url: str) -> dict[str, Any]:
    page = fetch_url_sync(url)
    summary_lines = [
        f"URL fetch: {page.get('url') or url}",
        f"Status: {page.get('status')}",
        "",
    ]
    if page.get("title"):
        summary_lines.append(page["title"])
        summary_lines.append("")
    if page.get("content"):
        summary_lines.append(page["content"])
    elif page.get("error"):
        summary_lines.append(f"Error: {page['error']}")
    return {
        "query": url,
        "source": "url-fetch",
        "results": [
            {
                "title": page.get("title") or url,
                "url": page.get("url") or url,
                "snippet": (page.get("content") or page.get("error") or "")[:400],
                "content": page.get("content") or "",
                "page": {
                    "ok": page.get("ok"),
                    "status": page.get("status"),
                    "title": page.get("title") or "",
                    "error": page.get("error") or "",
                },
            }
        ],
        "tried": ["url-fetch"],
        "summary": "\n".join(summary_lines).strip(),
    }


def _completed_task(task_id: str, query: str, payload: dict[str, Any], *, skill: str) -> dict[str, Any]:
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
                            "answer": payload.get("answer") or "",
                            "results": payload["results"],
                        }
                    )
                ],
            },
        ],
        "metadata": {"skillId": skill, "query": query, "source": payload.get("source")},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "agent": "search-agent",
        "version": "0.5.0",
        "search_mode": os.getenv("SEARCH_MODE", "auto"),
        "fetch_pages": os.getenv("SEARCH_FETCH_PAGES", "3"),
        "deerflow": "configured" if os.getenv("DEERFLOW_URL") else "off",
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
        if method in {"tasks/get", "tasks/cancel", "tasks/subscribe"}:
            if _COLLAB is not None:
                handled = _COLLAB.handle_control(method, params, _TASKS, req_id)
                if handled is not None:
                    return JSONResponse(handled)

        if method == "message/send":
            # P36.1: Extract idempotency key if present
            idempotency_key = params.get("idempotencyKey") or params.get("idempotency_key")
            
            # P36.1: Check if request already processed (Agent-side idempotency)
            if idempotency_key and idempotency_key in _IDEMPOTENCY_CACHE:
                cached = _IDEMPOTENCY_CACHE[idempotency_key]
                return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": cached})
            
            query = _extract_query(params)
            query = _extract_goal(query)
            skill = _skill_id(params)

            if skill == "url-fetch" or _looks_like_url(query):
                payload = _run_url_fetch(query)
                skill = "url-fetch"
            else:
                # P37.2: Use enhanced search if available and enabled
                use_enhanced = os.getenv("SEARCH_USE_ENHANCED", "false").lower() == "true"
                if use_enhanced and ENHANCED_SEARCH_AVAILABLE:
                    payload = run_search_sync(query)
                else:
                    payload = await run_search(query)
            
            task_id = str(uuid.uuid4())
            # A2A OS: inbound lineage + optional autonomous peer delegation.
            delegated = None
            if _COLLAB is not None:
                ctx = _COLLAB.context(params, task_id=task_id)
                delegated = _COLLAB.fetch(query, ctx)

            result = _completed_task(task_id, query, payload, skill=skill)
            if delegated:
                result.setdefault("metadata", {})["autonomous_delegation"] = delegated[:500]
            
            # P36.1: Cache result for idempotency
            if idempotency_key:
                _IDEMPOTENCY_CACHE[idempotency_key] = result

            if _COLLAB is not None:
                _COLLAB.after_complete(params, result)

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

        if method == "tasks/cancel":
            ok, task = _a2a_cancel(_TASKS, params.get("id"))
            if not ok:
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

    port = int(os.getenv("PORT", "8001"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
