from __future__ import annotations

import uuid
from typing import Any

import httpx

from .card import AgentCard, fetch_agent_card
from .models import Artifact, Message, Part, Task, TaskStatus


class A2AError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class A2AClient:
    """Enhanced A2A JSON-RPC client with streaming, cancellation, and delegation support."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 60.0,
        card: AgentCard | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._card = card

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
        return self.send_message(message, skill_id=skill_id, task_id=task_id)

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
    ) -> Task:
        params: dict[str, Any] = {"message": message.to_dict()}
        if task_id:
            params["id"] = task_id
        if skill_id:
            params["metadata"] = {"skillId": skill_id}
        if message.idempotency_key:
            params["idempotencyKey"] = message.idempotency_key
        # Lineage/governance are also mirrored at the top level so OS-side and
        # agent-side parsers that read params directly (not the nested message)
        # still see them. Explicit kwargs win; otherwise fall back to the message.
        correlation_id = correlation_id or message.correlation_id
        parent_task_id = parent_task_id or message.parent_task_id
        root_task_id = root_task_id or message.root_task_id
        depth = depth or message.depth
        if correlation_id:
            params["correlationId"] = correlation_id
        if parent_task_id:
            params["parentTaskId"] = parent_task_id
        if root_task_id:
            params["rootTaskId"] = root_task_id
        if depth > 0:
            params["depth"] = depth
        if message.caller_agent_id:
            params["callerAgentId"] = message.caller_agent_id
        if message.target_agent_id:
            params["targetAgentId"] = message.target_agent_id
        if message.visited_agents:
            params["visitedAgents"] = list(message.visited_agents)
        if message.governance_policy_id:
            params["governancePolicyId"] = message.governance_policy_id
        if message.deadline:
            params["deadline"] = message.deadline
        if message.callback_url:
            params["callbackUrl"] = message.callback_url

        result = self._rpc("message/send", params)
        if not isinstance(result, dict):
            raise A2AError(f"Unexpected message/send result type: {type(result)}")
        return Task.from_dict(result)

    def get_task(self, task_id: str) -> Task:
        result = self._rpc("tasks/get", {"id": task_id})
        if not isinstance(result, dict):
            raise A2AError(f"Unexpected tasks/get result type: {type(result)}")
        return Task.from_dict(result)

    def stream_tasks(
        self,
        skill_id: str | None = None,
        correlation_id: str | None = None,
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        depth: int = 0,
    ):
        """Stream tasks as they are created or updated."""
        params: dict[str, Any] = {}
        if skill_id:
            params["metadata"] = {"skillId": skill_id}
        if correlation_id:
            params["correlationId"] = correlation_id
        if parent_task_id:
            params["parentTaskId"] = parent_task_id
        if root_task_id:
            params["rootTaskId"] = root_task_id
        if depth > 0:
            params["depth"] = depth

        endpoint = self._rpc_endpoint()
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            with client.stream("POST", endpoint, json={"jsonrpc": "2.0", "method": "tasks/subscribe", "params": params}) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        yield line

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
            # Successful cancel returns the Task; treat known cancel states as True.
            if state in {"canceled", "cancelled"} or result.get("id"):
                return True
            return False
        raise A2AError(f"Unexpected tasks/cancel result type: {type(result)}")

    def delegate_task(
        self,
        task_id: str,
        target_agent_id: str,
        skill_id: str | None = None,
        correlation_id: str | None = None,
        parent_task_id: str | None = None,
        root_task_id: str | None = None,
        depth: int = 0,
    ) -> Task:
        """Delegate a task to another agent."""
        params: dict[str, Any] = {"taskId": task_id, "targetAgentId": target_agent_id}
        if skill_id:
            params["metadata"] = {"skillId": skill_id}
        if correlation_id:
            params["correlationId"] = correlation_id
        if parent_task_id:
            params["parentTaskId"] = parent_task_id
        if root_task_id:
            params["rootTaskId"] = root_task_id
        if depth > 0:
            params["depth"] = depth

        result = self._rpc("tasks/delegate", params)
        if not isinstance(result, dict):
            raise A2AError(f"Unexpected tasks/delegate result type: {type(result)}")
        return Task.from_dict(result)

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        endpoint = self._rpc_endpoint()
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
        with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
            resp = client.post(endpoint, json=payload)
            resp.raise_for_status()
            body = resp.json()

        if "error" in body and body["error"]:
            err = body["error"]
            raise A2AError(
                err.get("message") or "A2A RPC error",
                code=err.get("code"),
                data=err.get("data"),
            )
        # Always extract result from the body
        if isinstance(body, dict):
            return body.get("result")
        return body

    def _rpc_endpoint(self) -> str:
        # Prefer card.url when present; fall back to base_url root.
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


__all__ = [
    "A2AClient",
    "A2AError",
    "Artifact",
    "Message",
    "Part",
    "Task",
    "TaskStatus",
    "first_data_artifact",
    "first_text_artifact",
    "stream_tasks",
    "cancel_task",
    "delegate_task",
]
