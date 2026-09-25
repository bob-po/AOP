"""A2A OS — reusable server-side helpers for Agents.

Complements :mod:`agent_runtime.collaboration` (the client half). These helpers
make it trivial for any Agent's JSON-RPC endpoint to:

* extract inbound task lineage (``correlationId`` / ``rootTaskId`` /
  ``parentTaskId`` / ``depth`` / visited-agent chain) from a ``message/send``
  request and build a :class:`CallContext` the Agent can use to delegate onward;
* emit consistent JSON-RPC results/errors;
* handle ``tasks/cancel``, ``tasks/subscribe``, and optional completion callbacks.

Keeping this in the runtime package (not copy-pasted per agent) is what makes
every Agent a first-class Server *and* Client of the A2A network.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Iterator, Optional

from .collaboration import CallContext

logger = logging.getLogger(__name__)


def _first_key(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def extract_lineage(params: dict[str, Any]) -> dict[str, Any]:
    """Pull A2A lineage fields out of a JSON-RPC ``message/send`` params block.

    Lineage may sit at the top level of ``params`` or nested on the ``message``;
    both camelCase and snake_case wire names are accepted.
    """
    message = params.get("message") or {}
    src: dict[str, Any] = {**message, **params}
    visited = _first_key(src, "visitedAgents", "visited_agents")
    if isinstance(visited, str):
        visited = [v for v in visited.split(",") if v]
    return {
        "correlation_id": _first_key(src, "correlationId", "correlation_id"),
        "root_task_id": _first_key(src, "rootTaskId", "root_task_id"),
        "parent_task_id": _first_key(src, "parentTaskId", "parent_task_id"),
        "depth": int(_first_key(src, "depth") or 0),
        "visited_agents": list(visited or []),
        "caller_agent_id": _first_key(src, "callerAgentId", "caller_agent_id"),
        "governance_policy_id": _first_key(src, "governancePolicyId", "governance_policy_id"),
        "deadline": _first_key(src, "deadline"),
        "callback_url": _first_key(src, "callbackUrl", "callback_url"),
        "idempotency_key": _first_key(src, "idempotencyKey", "idempotency_key"),
    }


def inbound_context(
    params: dict[str, Any],
    *,
    agent_id: str,
    task_id: Optional[str] = None,
) -> CallContext:
    """Build a :class:`CallContext` for a task this Agent just received."""
    lin = extract_lineage(params)
    correlation_id = lin["correlation_id"] or task_id or agent_id
    return CallContext.from_inbound(
        agent_id=agent_id,
        correlation_id=str(correlation_id),
        task_id=task_id,
        root_task_id=lin["root_task_id"],
        parent_task_id=lin["parent_task_id"],
        depth=lin["depth"],
        visited_agents=[a for a in lin["visited_agents"] if a],
        governance_policy_id=lin["governance_policy_id"],
        deadline=lin["deadline"],
    )


def jsonrpc_result(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def jsonrpc_error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def find_cancel_targets(tasks: dict[str, Any], task_id: Optional[str]) -> list[str]:
    """Resolve cancel targets by exact id, or by rootTaskId / correlationId."""
    if not task_id:
        return []
    if task_id in tasks:
        return [task_id]
    matched: list[str] = []
    for tid, task in tasks.items():
        if not isinstance(task, dict):
            continue
        meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        roots = {
            task.get("rootTaskId"),
            task.get("correlationId"),
            meta.get("rootTaskId"),
            meta.get("correlationId"),
        }
        if task_id in {str(x) for x in roots if x}:
            matched.append(tid)
    return matched


def cancel_task(tasks: dict[str, Any], task_id: Optional[str]) -> tuple[bool, Optional[dict[str, Any]]]:
    """Mark matching locally-tracked task(s) canceled. Returns (ok, primary_task).

    Matches exact ``task_id`` first; otherwise cancels every in-memory task whose
    ``rootTaskId`` / ``correlationId`` equals the cancel id (OS → harness bridge).
    """
    targets = find_cancel_targets(tasks, task_id)
    if not targets:
        return False, None
    primary: Optional[dict[str, Any]] = None
    for tid in targets:
        task = tasks.get(tid)
        if not isinstance(task, dict):
            continue
        status = task.get("status")
        if isinstance(status, dict):
            status["state"] = "canceled"
        else:
            task["status"] = {"state": "canceled"}
        if primary is None:
            primary = task
    return primary is not None, primary


def _task_state(task: dict[str, Any]) -> str:
    status = task.get("status")
    if isinstance(status, dict):
        return str(status.get("state") or "submitted")
    return str(status or "submitted")


_TERMINAL = frozenset({"completed", "failed", "canceled", "cancelled"})


def subscribe_events(
    tasks: dict[str, Any],
    params: dict[str, Any],
    *,
    poll_interval: float = 0.25,
    timeout_s: float = 30.0,
) -> Iterator[dict[str, Any]]:
    """Yield task status events for ``tasks/subscribe`` (SSE / NDJSON friendly).

    Watches a local task store. If ``id`` is given, streams that task until it
    reaches a terminal state (or timeout). Otherwise emits a snapshot of matching
    tasks keyed by ``correlationId`` / ``rootTaskId``.
    """
    task_id = _first_key(params, "id", "taskId", "task_id")
    correlation_id = _first_key(params, "correlationId", "correlation_id")
    root_task_id = _first_key(params, "rootTaskId", "root_task_id")
    deadline = time.monotonic() + max(1.0, timeout_s)
    last_state: Optional[str] = None

    while time.monotonic() < deadline:
        if task_id:
            task = tasks.get(task_id)
            if task is None:
                yield {"event": "not_found", "taskId": task_id}
                return
            state = _task_state(task)
            if state != last_state:
                last_state = state
                yield {"event": "status", "taskId": task_id, "status": state, "task": task}
            if state in _TERMINAL:
                yield {"event": "final", "taskId": task_id, "status": state, "task": task}
                return
        else:
            matched = []
            for tid, task in list(tasks.items()):
                meta = task.get("metadata") or {}
                if correlation_id and (
                    meta.get("correlationId") != correlation_id
                    and task.get("correlationId") != correlation_id
                ):
                    continue
                if root_task_id and (
                    meta.get("rootTaskId") != root_task_id
                    and task.get("rootTaskId") != root_task_id
                ):
                    continue
                if correlation_id or root_task_id:
                    matched.append({"taskId": tid, "status": _task_state(task), "task": task})
            yield {"event": "snapshot", "tasks": matched, "count": len(matched)}
            return
        time.sleep(poll_interval)

    yield {"event": "timeout", "taskId": task_id, "lastStatus": last_state}


def notify_callback(callback_url: Optional[str], task: dict[str, Any], *, timeout: float = 10.0) -> bool:
    """Best-effort POST of a completed task to the caller's ``callbackUrl``.

    Failures are logged and swallowed — a callback miss must never fail the task.
    """
    if not callback_url:
        return False
    try:
        import httpx

        with httpx.Client(timeout=timeout) as client:
            resp = client.post(callback_url, json={"task": task})
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("callback notify failed (%s): %s", callback_url, exc)
        return False


def handle_control_method(
    method: Optional[str],
    params: dict[str, Any],
    *,
    req_id: Any,
    tasks: dict[str, Any],
    subscribe_timeout_s: float = 30.0,
) -> Optional[dict[str, Any]]:
    """Handle shared control-plane RPC methods. Returns a JSON-RPC body or None.

    Supported: ``tasks/get``, ``tasks/cancel``, ``tasks/subscribe`` (snapshot /
    single-task final event as a JSON-RPC result — agents that want true SSE
    should stream :func:`subscribe_events` themselves).
    """
    if method == "tasks/get":
        task_id = _first_key(params, "id", "taskId", "task_id")
        task = tasks.get(task_id) if task_id else None
        if not task:
            return jsonrpc_error(req_id, -32001, f"Task not found: {task_id}")
        return jsonrpc_result(req_id, task)

    if method == "tasks/cancel":
        ok, task = cancel_task(tasks, _first_key(params, "id", "taskId", "task_id"))
        if not ok:
            return jsonrpc_error(req_id, -32001, "Task not found")
        return jsonrpc_result(req_id, task)

    if method == "tasks/subscribe":
        # Synchronous snapshot / wait-for-terminal for JSON-RPC clients that
        # cannot stream. Returns the last event as the RPC result; full event
        # streams use subscribe_events() with an SSE response.
        events = list(subscribe_events(tasks, params, timeout_s=subscribe_timeout_s))
        return jsonrpc_result(req_id, {"events": events, "count": len(events)})

    return None


def sse_bytes(events: Iterator[dict[str, Any]]) -> Iterator[bytes]:
    """Encode subscribe events as Server-Sent Events frames."""
    for ev in events:
        payload = json.dumps(ev, default=str)
        yield f"event: {ev.get('event', 'message')}\ndata: {payload}\n\n".encode("utf-8")


__all__ = [
    "extract_lineage",
    "inbound_context",
    "jsonrpc_result",
    "jsonrpc_error",
    "find_cancel_targets",
    "cancel_task",
    "subscribe_events",
    "notify_callback",
    "handle_control_method",
    "sse_bytes",
]
