"""A2A OS — reusable server-side helpers for Agents.

Complements :mod:`agent_runtime.collaboration` (the client half). These helpers
make it trivial for any Agent's JSON-RPC endpoint to:

* extract inbound task lineage (``correlationId`` / ``rootTaskId`` /
  ``parentTaskId`` / ``depth`` / visited-agent chain) from a ``message/send``
  request and build a :class:`CallContext` the Agent can use to delegate onward;
* emit consistent JSON-RPC results/errors;
* handle ``tasks/cancel`` and optional completion callbacks.
  (``tasks/subscribe`` / ``tasks/delegate`` were removed — use ``message/stream``
  or OS discover/route.)

Keeping this in the runtime package (not copy-pasted per agent) is what makes
every Agent a first-class Server *and* Client of the A2A network.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from .collaboration import CallContext

logger = logging.getLogger(__name__)


def _first_key(d: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def extract_lineage(params: dict[str, Any]) -> dict[str, Any]:
    """Pull A2A lineage fields out of a JSON-RPC ``message/send`` params block.

    Preferred home is ``params.metadata`` / ``message.metadata`` (official
    extension surface). Deprecated top-level fields on ``params`` / ``message``
    are still accepted for older AOP clients.
    """
    message = params.get("message") or {}
    msg_meta = message.get("metadata") if isinstance(message, dict) else None
    params_meta = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
    if not isinstance(msg_meta, dict):
        msg_meta = {}
    # Precedence: params.metadata > message.metadata > top-level params > message
    src: dict[str, Any] = {**message, **params, **msg_meta, **params_meta}
    visited = _first_key(src, "visitedAgents", "visited_agents")
    if isinstance(visited, str):
        visited = [v for v in visited.split(",") if v]
    callback = _first_key(src, "callbackUrl", "callback_url")
    push = _first_key(src, "pushNotificationConfig", "push_notification_config")
    if not callback and isinstance(push, dict):
        callback = push.get("url")
    return {
        "correlation_id": _first_key(src, "correlationId", "correlation_id"),
        "root_task_id": _first_key(src, "rootTaskId", "root_task_id"),
        "parent_task_id": _first_key(src, "parentTaskId", "parent_task_id"),
        "depth": int(_first_key(src, "depth") or 0),
        "visited_agents": list(visited or []),
        "caller_agent_id": _first_key(src, "callerAgentId", "caller_agent_id"),
        "governance_policy_id": _first_key(src, "governancePolicyId", "governance_policy_id"),
        "deadline": _first_key(src, "deadline"),
        "callback_url": callback,
        "idempotency_key": _first_key(src, "idempotencyKey", "idempotency_key"),
        "push_notification_config": push if isinstance(push, dict) else (
            {"url": callback} if callback else None
        ),
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


def notify_callback(
    callback_url: Optional[str],
    task: dict[str, Any],
    *,
    timeout: float = 10.0,
    push_notification_config: Optional[dict[str, Any]] = None,
) -> bool:
    """Best-effort POST of a completed task to the caller's push URL.

    Accepts legacy ``callbackUrl`` or official-shaped
    ``pushNotificationConfig.url``. Failures are logged and swallowed.
    Blocks unsafe destinations (non-http(s), link-local/metadata, and by
    default private/loopback unless ``AOP_CALLBACK_ALLOW_PRIVATE=1``).
    """
    url = callback_url
    if not url and isinstance(push_notification_config, dict):
        url = push_notification_config.get("url")
    if not url:
        return False
    if not _callback_url_allowed(str(url)):
        logger.warning("callback notify blocked (unsafe url): %s", url)
        return False
    try:
        import httpx

        # Official-ish payload: task at top level; keep ``{"task": ...}`` wrapper
        # for AOP callers that already expect it.
        body = {"task": task, **{k: v for k, v in task.items() if k in {"id", "status", "artifacts"}}}
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(str(url), json=body)
            resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("callback notify failed (%s): %s", url, exc)
        return False


def _callback_url_allowed(url: str) -> bool:
    from urllib.parse import urlparse
    import ipaddress
    import os
    import socket

    try:
        parsed = urlparse(url.strip())
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host in {"metadata.google.internal", "metadata"}:
        return False

    allow_private = os.getenv("AOP_CALLBACK_ALLOW_PRIVATE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    def _ip_ok(ip: ipaddress._BaseAddress) -> bool:
        if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return False
        if ip.is_loopback or ip.is_private:
            return allow_private
        return True

    try:
        ip = ipaddress.ip_address(host)
        return _ip_ok(ip)
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if not _ip_ok(ip):
            return False
    return True


def handle_control_method(
    method: Optional[str],
    params: dict[str, Any],
    *,
    req_id: Any,
    tasks: dict[str, Any],
    subscribe_timeout_s: float = 30.0,
) -> Optional[dict[str, Any]]:
    """Handle shared control-plane RPC methods. Returns a JSON-RPC body or None.

    Supported: ``tasks/get``, ``tasks/cancel``.
    Removed: ``tasks/subscribe``, ``tasks/delegate`` (return -32601).
    Agents that need streaming should use ``message/stream`` /
    :func:`format_sse_frame`.
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

    if method in {"tasks/subscribe", "tasks/delegate"}:
        return jsonrpc_error(
            req_id,
            -32601,
            f"Method not found: {method} (removed; use message/stream or OS discover/route)",
        )

    return None


def format_sse_frame(event: str, data: Any) -> bytes:
    """Encode one Server-Sent Events frame for ``message/stream``."""
    payload = json.dumps(data, default=str)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


__all__ = [
    "extract_lineage",
    "inbound_context",
    "jsonrpc_result",
    "jsonrpc_error",
    "find_cancel_targets",
    "cancel_task",
    "notify_callback",
    "handle_control_method",
    "format_sse_frame",
]
