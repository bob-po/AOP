"""Image Agent — text-to-image stub returning SVG artifact."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
app = FastAPI(title="AOP Image Agent", version="0.1.0")
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


def _svg_for(prompt: str) -> str:
    title = escape(prompt[:48] + ("…" if len(prompt) > 48 else ""))
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#0f1c18"/>
      <stop offset="100%" stop-color="#1fbf7a"/>
    </linearGradient>
  </defs>
  <rect width="960" height="540" fill="url(#g)"/>
  <text x="48" y="80" fill="#e8f2ee" font-family="Georgia, serif" font-size="36">A2A OS · Image Stub</text>
  <text x="48" y="140" fill="#c5ddd3" font-family="monospace" font-size="18">{title}</text>
  <circle cx="780" cy="380" r="90" fill="#3dffa8" opacity="0.35"/>
</svg>"""


def run_image(prompt: str) -> dict[str, Any]:
    svg = _svg_for(prompt)
    return {
        "prompt": prompt,
        "format": "svg",
        "width": 960,
        "height": 540,
        "svg": svg,
        "note": "Stub generator. Swap with ComfyUI backend later.",
    }


def _completed_task(task_id: str, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "promo.svg",
                "description": "Generated SVG image",
                "parts": [{"type": "text", "text": payload["svg"]}],
            },
            {
                "artifactId": str(uuid.uuid4()),
                "name": "image-meta",
                "parts": [
                    {
                        "type": "data",
                        "data": {k: v for k, v in payload.items() if k != "svg"},
                    }
                ],
            },
        ],
        "metadata": {"skillId": "text-to-image", "prompt": prompt},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "agent": "image-agent"}


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
            prompt = _extract_query(params)
            payload = run_image(prompt)
            result = _completed_task(str(uuid.uuid4()), prompt, payload)
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

    port = int(os.getenv("PORT", "8005"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
