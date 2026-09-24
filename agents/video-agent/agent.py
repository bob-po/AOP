"""Video Agent — text-to-video stub returning storyboard metadata."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# A2A OS: make this Agent a first-class citizen — Server *and* Client.
try:
    from agent_runtime.agent_collab import AgentCollaborator
    from agent_runtime.a2a_server import cancel_task as _a2a_cancel
    _COLLAB = AgentCollaborator(agent_id="video-agent")
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
app = FastAPI(title="AOP Video Agent", version="0.1.0")
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


def run_video(prompt: str) -> dict[str, Any]:
    scenes = [
        {"t": "0:00", "shot": "Title card", "narration": f"Introducing {prompt[:40]}"},
        {"t": "0:08", "shot": "Product walkthrough", "narration": "Show multi-agent orchestration flow"},
        {"t": "0:20", "shot": "Results montage", "narration": "Artifacts, reports, and media outputs"},
        {"t": "0:30", "shot": "CTA", "narration": "Run it on A2A OS"},
    ]
    storyboard = "\n".join(f"- [{s['t']}] {s['shot']}: {s['narration']}" for s in scenes)
    return {
        "prompt": prompt,
        "duration_sec": 32,
        "format": "storyboard-stub",
        "scenes": scenes,
        "storyboard": storyboard,
        "note": "Stub generator. Swap with AIVE / real video backend later.",
    }


def _completed_task(task_id: str, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "video-storyboard",
                "parts": [{"type": "text", "text": payload["storyboard"]}],
            },
            {
                "artifactId": str(uuid.uuid4()),
                "name": "video-meta",
                "parts": [{"type": "data", "data": payload}],
            },
        ],
        "metadata": {"skillId": "text-to-video", "prompt": prompt},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": "video-agent"}


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
            
            prompt = _extract_query(params)
            payload = run_video(prompt)
            task_id = str(uuid.uuid4())
            # A2A OS: inbound lineage + optional autonomous peer delegation.
            delegated = None
            if _COLLAB is not None:
                ctx = _COLLAB.context(params, task_id=task_id)
                delegated = _COLLAB.fetch(prompt, ctx)

            result = _completed_task(task_id, prompt, payload)
            if delegated:
                result.setdefault("metadata", {})["autonomous_delegation"] = delegated[:500]
            
            # P36.1: Cache result for idempotency
            if idempotency_key:
                _IDEMPOTENCY_CACHE[idempotency_key] = result

            if _COLLAB is not None:
                _COLLAB.after_complete(params, result)

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

    port = int(os.getenv("PORT", "8006"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
