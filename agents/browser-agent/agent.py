"""Browser Agent — Playwright Chromium with stub fallback (Phase 27/29)."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from browse import playwright_available, resolve_backend, run_browse

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
app = FastAPI(title="AOP Browser Agent", version="0.2.0")
_TASKS: dict[str, dict[str, Any]] = {}


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


def _completed_task(task_id: str, instruction: str, payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("snippet") if payload.get("ok") else f"error: {payload.get('error')}"
    # Keep screenshots out of text artifact; include in data if present
    data = {k: v for k, v in payload.items() if k != "screenshot_b64"}
    if payload.get("screenshot_b64"):
        data["screenshot_b64_len"] = len(payload["screenshot_b64"])
        data["has_screenshot"] = True
    artifacts: list[dict[str, Any]] = [
        {
            "artifactId": str(uuid.uuid4()),
            "name": "browse-summary",
            "parts": [{"type": "text", "text": str(text)}],
        },
        {
            "artifactId": str(uuid.uuid4()),
            "name": "browse-meta",
            "parts": [{"type": "data", "data": data}],
        },
    ]
    if payload.get("screenshot_b64") and os.getenv("BROWSER_SCREENSHOT_INLINE", "0").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        artifacts.append(
            {
                "artifactId": str(uuid.uuid4()),
                "name": "screenshot.png.b64",
                "parts": [{"type": "text", "text": payload["screenshot_b64"]}],
            }
        )
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": artifacts,
        "metadata": {
            "skillId": "browser-automation",
            "instruction": instruction,
            "backend": payload.get("backend"),
        },
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent": "browser-agent",
        "version": "0.2.0",
        "backend": resolve_backend(),
        "playwright": playwright_available(),
        "mode": os.getenv("BROWSER_MODE", "auto"),
        "seccomp_profile": os.getenv("AOP_SECCOMP_PROFILE", "browser-agent"),
        "egress_allowlist": os.getenv("BROWSER_EGRESS_ALLOWLIST", "") or "*",
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
            instruction = _extract_query(params)
            payload = await asyncio.to_thread(run_browse, instruction)
            result = _completed_task(str(uuid.uuid4()), instruction, payload)
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

    port = int(os.getenv("PORT", "8008"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
