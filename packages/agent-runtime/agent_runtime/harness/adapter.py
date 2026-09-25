"""FastAPI factory: A2A shell that delegates execution to a HarnessRunner."""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from ..agent_collab import AgentCollaborator
from ..a2a_server import extract_lineage, find_cancel_targets
from .cost import attach_usage, report_usage_to_os
from .events import apply_event, finalize_task, new_working_task, utc_now
from .protocol import (
    HarnessEvent,
    HarnessEventType,
    HarnessResult,
    HarnessRunner,
    HarnessStatus,
)

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
except ImportError:  # pragma: no cover
    FastAPI = None  # type: ignore[misc, assignment]
    Request = None  # type: ignore[misc, assignment]
    JSONResponse = None  # type: ignore[misc, assignment]


def load_agent_card(card_path: str | Path, *, agent_url: Optional[str] = None) -> dict[str, Any]:
    path = Path(card_path)
    card = json.loads(path.read_text(encoding="utf-8"))
    override = agent_url or os.getenv("AGENT_URL")
    if override:
        card["url"] = override if override.endswith("/") else f"{override}/"
    return card


def _extract_text(message: dict[str, Any]) -> str:
    parts = message.get("parts") or []
    texts = [p.get("text", "").strip() for p in parts if p.get("type") == "text" and p.get("text")]
    if not texts:
        raise ValueError("message.parts must include at least one text part")
    return " ".join(texts).strip()


def _skill_id(params: dict[str, Any], card: dict[str, Any]) -> str:
    metadata = params.get("metadata") or {}
    sid = metadata.get("skillId") or metadata.get("skill_id")
    if sid:
        return str(sid)
    skills = card.get("skills") or []
    if skills:
        return str(skills[0].get("id") or "default")
    # No skills on card — pass-through agent identity / default.
    return str(card.get("agentKey") or card.get("name") or "default")


def _skill_allowed(skill_id: str, card: dict[str, Any]) -> bool:
    skills = card.get("skills") or []
    if not skills:
        return True  # skill-less virtual agents accept any / no skillId
    allowed = {str(s.get("id")) for s in skills if s.get("id")}
    return skill_id in allowed


def create_harness_app(
    *,
    agent_id: str,
    runner: HarnessRunner,
    card: dict[str, Any] | None = None,
    card_path: str | Path | None = None,
    system_prompt: str | None = None,
    enable_heartbeat: bool = True,
    heartbeat_interval_s: float = 15.0,
    title: str | None = None,
    version: str = "0.1.0",
) -> Any:
    """Build a FastAPI app that speaks A2A and runs tasks via ``runner``."""
    if FastAPI is None or Request is None or JSONResponse is None:
        raise ImportError(
            "create_harness_app requires fastapi — pip install fastapi uvicorn"
        )

    if card is None:
        if not card_path:
            raise ValueError("card or card_path is required")
        card = load_agent_card(card_path)

    tasks: dict[str, dict[str, Any]] = {}
    idempotency_cache: dict[str, dict[str, Any]] = {}
    collab = AgentCollaborator(agent_id=agent_id)
    sys_prompt = system_prompt or ""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if enable_heartbeat:
            collab.start_heartbeat(
                interval_s=heartbeat_interval_s,
                version=version,
                capabilities={
                    "harness": True,
                    "streaming": bool((card.get("capabilities") or {}).get("streaming")),
                },
            )
        yield
        collab.stop_heartbeat()

    app = FastAPI(
        title=title or f"AOP Harness ({agent_id})",
        version=version,
        lifespan=lifespan,
    )
    app.state.agent_id = agent_id
    app.state.card = card
    app.state.runner = runner
    app.state.tasks = tasks
    app.state.collab = collab
    app.state.system_prompt = sys_prompt

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "agent": agent_id,
            "version": version,
            "harness": True,
            "runner": type(runner).__name__,
        }

    @app.get("/.well-known/agent-card.json")
    @app.get("/.well-known/agent.json")
    async def agent_card() -> JSONResponse:
        live = dict(card)
        override = os.getenv("AGENT_URL")
        if override:
            live["url"] = override if override.endswith("/") else f"{override}/"
        return JSONResponse(live, media_type="application/json")

    @app.post("/")
    @app.post("/a2a")
    async def a2a_rpc(request: Request) -> JSONResponse:
        body = await request.json()
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        try:
            if method in {"tasks/get", "tasks/cancel", "tasks/subscribe"}:
                if method == "tasks/cancel":
                    tid = params.get("id") or params.get("taskId") or params.get("task_id")
                    cancel_key = str(tid) if tid else ""
                    # Kill harness processes for exact id and/or OS root/correlation match.
                    for target in find_cancel_targets(tasks, cancel_key) or (
                        [cancel_key] if cancel_key else []
                    ):
                        try:
                            await runner.cancel(str(target))
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("[%s] runner.cancel(%s) failed: %s", agent_id, target, exc)
                handled = collab.handle_control(method, params, tasks, req_id)
                if handled is not None:
                    return JSONResponse(handled)

            if method == "message/send":
                idem = params.get("idempotencyKey") or params.get("idempotency_key")
                if idem and idem in idempotency_cache:
                    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": idempotency_cache[idem]})

                message = params.get("message") or {}
                _extract_text(message)
                skill = _skill_id(params, card)
                if not _skill_allowed(skill, card):
                    return JSONResponse(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32602, "message": f"Unsupported skill: {skill}"},
                        }
                    )

                # Prefer client-supplied id so OS can cancel with a known key.
                client_id = params.get("id") or params.get("taskId") or params.get("task_id")
                task_id = str(client_id) if client_id else str(uuid.uuid4())
                lin = extract_lineage(params)
                ctx = collab.context(params, task_id=task_id)
                task = new_working_task(
                    task_id,
                    skill_id=skill,
                    correlation_id=lin.get("correlation_id") or (ctx.correlation_id if ctx else None),
                    root_task_id=lin.get("root_task_id"),
                    parent_task_id=lin.get("parent_task_id"),
                )
                task["metadata"]["agentId"] = agent_id
                if sys_prompt:
                    task["metadata"]["systemPromptBytes"] = len(sys_prompt)
                tasks[task_id] = task
                collab.bump_active(1)

                async def _on_event(event: HarnessEvent) -> None:
                    apply_event(tasks[task_id], event)

                run_message = dict(message)
                run_message.setdefault("metadata", {})
                if isinstance(run_message["metadata"], dict) and sys_prompt:
                    run_message["metadata"]["systemPrompt"] = sys_prompt

                try:
                    result = await runner.run(
                        task_id=task_id,
                        message=run_message,
                        skill_id=skill,
                        on_event=_on_event,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[%s] harness run failed", agent_id)
                    result = HarnessResult(
                        text="",
                        status=HarnessStatus.FAILED,
                        error=str(exc),
                        skill_id=skill,
                    )
                    await _on_event(
                        HarnessEvent(
                            type=HarnessEventType.ERROR,
                            task_id=task_id,
                            timestamp=utc_now(),
                            payload={"error": str(exc)},
                        )
                    )

                current = tasks.get(task_id) or task
                state = (
                    (current.get("status") or {}).get("state")
                    if isinstance(current.get("status"), dict)
                    else None
                )
                if state in {"canceled", "cancelled"}:
                    result = HarnessResult(
                        text=result.text,
                        data=result.data,
                        usage=result.usage,
                        status=HarnessStatus.CANCELED,
                        error=result.error or "canceled",
                        skill_id=skill,
                    )
                elif result.status == HarnessStatus.CANCELED:
                    # Runner aborted without store update — mirror into task store.
                    if isinstance(current.get("status"), dict):
                        current["status"]["state"] = "canceled"
                    else:
                        current["status"] = {"state": "canceled"}

                finalize_task(current, result)
                attach_usage(current, result.usage)
                report_usage_to_os(
                    task_id=task_id,
                    agent_id=agent_id,
                    usage=result.usage,
                    root_task_id=current.get("rootTaskId"),
                    correlation_id=current.get("correlationId"),
                    os_url=collab.os_url or None,
                    api_key=collab.api_key,
                )
                collab.bump_active(-1)

                if idem:
                    idempotency_cache[idem] = current
                collab.after_complete(params, current)
                return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": current})

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
            logger.exception("[%s] rpc error", agent_id)
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32603, "message": f"Internal error: {exc}"},
                }
            )

    return app


__all__ = ["create_harness_app", "load_agent_card"]
