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
    """Minimal A2A JSON-RPC client for Phase 1 (message/send)."""

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

    def send_text(self, text: str, *, skill_id: str | None = None) -> Task:
        message = Message(
            role="user",
            parts=[Part(type="text", text=text)],
            message_id=str(uuid.uuid4()),
        )
        return self.send_message(message, skill_id=skill_id)

    def send_message(self, message: Message, *, skill_id: str | None = None) -> Task:
        params: dict[str, Any] = {"message": message.to_dict()}
        if skill_id:
            params["metadata"] = {"skillId": skill_id}

        result = self._rpc("message/send", params)
        if not isinstance(result, dict):
            raise A2AError(f"Unexpected message/send result type: {type(result)}")
        return Task.from_dict(result)

    def get_task(self, task_id: str) -> Task:
        result = self._rpc("tasks/get", {"id": task_id})
        if not isinstance(result, dict):
            raise A2AError(f"Unexpected tasks/get result type: {type(result)}")
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
        return body.get("result")

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
]
