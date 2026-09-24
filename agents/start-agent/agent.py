"""Start Agent — A2A Server+Client façade over DeployPilot (Phase 2).

DeployPilot itself remains a TypeScript CLI. This FastAPI process exposes the
standard A2A JSON-RPC surface (message/send, tasks/get|cancel|subscribe) and
``AgentCollaborator`` so start-agent is a first-class peer in the Agent network
(10/10 Client-ization).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

try:
    from agent_runtime.agent_collab import AgentCollaborator
    from agent_runtime.a2a_server import cancel_task as _a2a_cancel

    _COLLAB = AgentCollaborator(agent_id="start-agent")
except ImportError:  # pragma: no cover
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
app = FastAPI(title="AOP Start Agent", version="0.1.0")
_TASKS: dict[str, dict[str, Any]] = {}
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


def _skill_id(params: dict[str, Any]) -> str:
    metadata = params.get("metadata") or {}
    return str(metadata.get("skillId") or metadata.get("skill_id") or "project-deploy")


_TARGET_RE = re.compile(
    r"(https?://[^\s]+|[A-Za-z]:\\[^\s]+|/(?:[^\s]+)|\\./[^\s]+|\./[^\s]+)",
    re.I,
)


def _plan_deploy(goal: str) -> dict[str, Any]:
    """Heuristic deploy plan; optionally shells out to DeployPilot when present."""
    m = _TARGET_RE.search(goal or "")
    target = m.group(1) if m else None
    mode = "docker" if "docker" in (goal or "").lower() else "auto"
    plan = {
        "goal": goal,
        "target": target,
        "mode": mode,
        "steps": [
            "analyze project type (node/python/compose)",
            "plan build + start",
            "health-check resulting URL",
        ],
        "engine": "heuristic",
        "deploypilot_available": bool(shutil.which("deploypilot") or shutil.which("npx")),
    }

    # Opt-in real CLI invocation (never invent URLs; only surface CLI output).
    if os.getenv("START_AGENT_INVOKE_CLI", "").lower() in {"1", "true", "yes"} and target:
        cli = shutil.which("deploypilot")
        cmd = [cli, "deploy", target, "--mode", mode] if cli else ["npx", "--yes", "deploypilot", "deploy", target]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=float(os.getenv("START_AGENT_CLI_TIMEOUT", "120")),
                cwd=str(ROOT),
                check=False,
            )
            plan["engine"] = "deploypilot-cli"
            plan["cli_exit"] = proc.returncode
            plan["cli_stdout"] = (proc.stdout or "")[-4000:]
            plan["cli_stderr"] = (proc.stderr or "")[-2000:]
        except Exception as exc:  # noqa: BLE001
            plan["cli_error"] = str(exc)
    return plan


def _completed_task(task_id: str, goal: str, payload: dict[str, Any]) -> dict[str, Any]:
    summary = (
        f"Start-agent plan for {payload.get('target') or 'unspecified target'} "
        f"(mode={payload.get('mode')}, engine={payload.get('engine')})"
    )
    task = {
        "id": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "deploy-plan",
                "parts": [
                    {"type": "text", "text": summary},
                    {"type": "data", "data": payload},
                ],
            }
        ],
        "metadata": {"skillId": "project-deploy", "agent": "start-agent"},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "agent": "start-agent",
        "engine": "DeployPilot",
        "a2a_client": _COLLAB is not None,
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
            idempotency_key = params.get("idempotencyKey") or params.get("idempotency_key")
            if idempotency_key and idempotency_key in _IDEMPOTENCY_CACHE:
                cached = _IDEMPOTENCY_CACHE[idempotency_key]
                return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": cached})

            goal = _extract_query(params)
            _skill_id(params)
            payload = _plan_deploy(goal)

            task_id = str(uuid.uuid4())
            delegated = None
            if _COLLAB is not None:
                ctx = _COLLAB.context(params, task_id=task_id)
                delegated = _COLLAB.fetch(goal, ctx)

            result = _completed_task(task_id, goal, payload)
            if delegated:
                result.setdefault("metadata", {})["autonomous_delegation"] = delegated[:500]
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
            {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": str(exc)}}
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

    port = int(os.getenv("PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port)
