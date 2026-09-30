from __future__ import annotations

import json
import uuid
from typing import Any, Iterator

import httpx

from .card import AgentCard, fetch_agent_card
from .models import Message, Part, Task
from .protocol import TERMINAL_TASK_STATES


class A2AError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


def _merge_params_metadata(
    params: dict[str, Any],
    message: Message,
    *,
    skill_id: str | None = None,
    async_mode: bool = False,
    correlation_id: str | None = None,
    parent_task_id: str | None = None,
    root_task_id: str | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    """Build message/send params: official core + metadata extensions only."""
    msg = message.to_dict()
    params["message"] = msg

    meta: dict[str, Any] = dict(msg.get("metadata") or {})
    if skill_id:
        meta["skillId"] = skill_id
    if async_mode:
        meta["async"] = True

    correlation_id = correlation_id or message.correlation_id
    parent_task_id = parent_task_id or message.parent_task_id
    root_task_id = root_task_id or message.root_task_id
    depth = depth or message.depth
    if correlation_id:
        meta.setdefault("correlationId", correlation_id)
    if parent_task_id:
        meta.setdefault("parentTaskId", parent_task_id)
    if root_task_id:
        meta.setdefault("rootTaskId", root_task_id)
    if depth > 0:
        meta.setdefault("depth", depth)
    if message.caller_agent_id:
        meta.setdefault("callerAgentId", message.caller_agent_id)
    if message.target_agent_id:
        meta.setdefault("targetAgentId", message.target_agent_id)
    if message.visited_agents:
        meta.setdefault("visitedAgents", list(message.visited_agents))
    if message.governance_policy_id:
        meta.setdefault("governancePolicyId", message.governance_policy_id)
    if message.deadline:
        meta.setdefault("deadline", message.deadline)
    if message.callback_url:
        meta.setdefault("callbackUrl", message.callback_url)
        meta.setdefault("pushNotificationConfig", {"url": message.callback_url})
    if message.idempotency_key:
        meta.setdefault("idempotencyKey", message.idempotency_key)

    if meta:
        params["metadata"] = meta
        msg["metadata"] = meta

    return params


class A2AClient:
    """A2A JSON-RPC client aligned with a2aproject/A2A wire shapes."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        card: AgentCard | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._card = card
        self._http = http_client
        self._owns_http = http_client is None

    def _client(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=self.timeout, follow_redirects=True)
            self._owns_http = True
        return self._http

    def close(self) -> None:
        if self._owns_http and self._http is not None:
            self._http.close()
            self._http = None

    def __enter__(self) -> "A2AClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def card(self) -> AgentCard:
        if self._card is None:
            self._card = fetch_agent_card(self.base_url, timeout=self.timeout)
        return self._card

    def refresh_card(self) -> AgentCard:
        self._card = fetch_agent_card(self.base_url, timeout=self.timeout)
        return self._card

    def send_text(
        self,
        text: str,
        *,
        skill_id: str | None = None,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        depth: int = 0,
        caller_agent_id: str | None = None,
        target_agent_id: str | None = None,
        visited_agents: list[str] | None = None,
        governance_policy_id: str | None = None,
        deadline: str | None = None,
        callback_url: str | None = None,
        task_id: str | None = None,
        async_mode: bool = False,
    ) -> Task:
        message = Message(
            role="user",
            parts=[Part(type="text", text=text)],
            message_id=str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            correlation_id=correlation_id,
            parent_task_id=parent_task_id,
            root_task_id=root_task_id,
            depth=depth,
            caller_agent_id=caller_agent_id,
            target_agent_id=target_agent_id,
            visited_agents=list(visited_agents or []),
            governance_policy_id=governance_policy_id,
            deadline=deadline,
            callback_url=callback_url,
        )
        return self.send_message(
            message,
            skill_id=skill_id,
            task_id=task_id,
            async_mode=async_mode,
        )

    def send_message(
        self,
        message: Message,
        *,
        skill_id: str | None = None,
        correlation_id: str | None = None,
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        depth: int = 0,
        task_id: str | None = None,
        async_mode: bool = False,
    ) -> Task:
        params: dict[str, Any] = {}
        if task_id:
            params["id"] = task_id
        _merge_params_metadata(
            params,
            message,
            skill_id=skill_id,
            async_mode=async_mode,
            correlation_id=correlation_id,
            parent_task_id=parent_task_id,
            root_task_id=root_task_id,
            depth=depth,
        )
        result = self._rpc("message/send", params)
        if not isinstance(result, dict):
            raise A2AError(f"Unexpected message/send result type: {type(result)}")
        return Task.from_dict(result)

    def stream_message(
        self,
        message: Message,
        *,
        skill_id: str | None = None,
        task_id: str | None = None,
        correlation_id: str | None = None,
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        depth: int = 0,
    ) -> Iterator[dict[str, Any]]:
        """Call ``message/stream`` and yield parsed SSE ``data`` JSON objects."""
        params: dict[str, Any] = {}
        if task_id:
            params["id"] = task_id
        _merge_params_metadata(
            params,
            message,
            skill_id=skill_id,
            async_mode=False,
            correlation_id=correlation_id,
            parent_task_id=parent_task_id,
            root_task_id=root_task_id,
            depth=depth,
        )
        endpoint = self._rpc_endpoint()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/stream",
            "params": params,
        }
        with self._client().stream("POST", endpoint, json=payload) as resp:
            resp.raise_for_status()
            event_name = "message"
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("event:"):
                    event_name = line[6:].strip() or "message"
                    continue
                if line.startswith("data:"):
                    raw = line[5:].strip()
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = {"raw": raw}
                    if isinstance(data, dict):
                        data.setdefault("event", event_name)
                    yield data if isinstance(data, dict) else {"event": event_name, "data": data}

    def get_task(self, task_id: str) -> Task:
        result = self._rpc("tasks/get", {"id": task_id})
        if not isinstance(result, dict):
            raise A2AError(f"Unexpected tasks/get result type: {type(result)}")
        return Task.from_dict(result)

    def poll_task(
        self,
        task_id: str,
        *,
        timeout_s: float = 900.0,
        poll_interval_s: float = 2.0,
        terminal: frozenset[str] | None = None,
    ) -> Task:
        """Poll ``tasks/get`` until a terminal (or interrupted) state."""
        import time

        done = terminal or (TERMINAL_TASK_STATES | {"input-required", "auth-required"})
        deadline = time.monotonic() + max(1.0, float(timeout_s))
        last: Task | None = None
        while time.monotonic() < deadline:
            last = self.get_task(task_id)
            state = getattr(last.status, "value", str(last.status)).lower()
            if state in done:
                return last
            time.sleep(max(0.2, float(poll_interval_s)))
        raise TimeoutError(f"A2A poll timed out after {timeout_s}s for task {task_id}")

    def stream_tasks(self, *args: Any, **kwargs: Any) -> Iterator[dict[str, Any]]:
        """Removed. Use :meth:`stream_message` / ``message/stream``."""
        raise A2AError(
            "tasks/subscribe was removed; use message/stream via stream_message()",
            code=-32601,
        )

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a task. Accepts bool or Task-shaped dict from the agent."""
        result = self._rpc("tasks/cancel", {"id": task_id})
        if isinstance(result, bool):
            return result
        if isinstance(result, dict):
            status = result.get("status")
            if isinstance(status, dict):
                state = str(status.get("state") or "").lower()
            else:
                state = str(status or "").lower()
            if state in {"canceled", "cancelled"} or result.get("id"):
                return True
            return False
        raise A2AError(f"Unexpected tasks/cancel result type: {type(result)}")

    def delegate_task(self, *args: Any, **kwargs: Any) -> Task:
        """Removed AOP-only RPC. Use OS discover/route + :meth:`send_message`."""
        raise A2AError(
            "tasks/delegate was removed; use OS /v1/discover|/v1/route + message/send",
            code=-32601,
        )

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        endpoint = self._rpc_endpoint()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        resp = self._client().post(endpoint, json=payload)
        resp.raise_for_status()
        body = resp.json()

        if "error" in body and body["error"]:
            err = body["error"]
            raise A2AError(
                err.get("message") or "A2A RPC error",
                code=err.get("code"),
                data=err.get("data"),
            )
        if isinstance(body, dict):
            return body.get("result")
        return body

    def _rpc_endpoint(self) -> str:
        url = (self._card.url if self._card else None) or f"{self.base_url}/"
        return url if url.endswith("/") else f"{url}/"


def first_text_artifact(task: Task) -> str | None:
    for artifact in task.artifacts:
        text = artifact.text()
        if text:
            return text
    return None


def first_data_artifact(task: Task) -> dict[str, Any] | None:
    for artifact in task.artifacts:
        data = artifact.data()
        if data is not None:
            return data
    return None
