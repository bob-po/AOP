from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    SUBMITTED = "submitted"
    WORKING = "working"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    INPUT_REQUIRED = "input-required"


@dataclass
class Part:
    type: str  # text | data | file
    text: str | None = None
    data: dict[str, Any] | None = None
    file: dict[str, Any] | None = None
    mime_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type}
        if self.text is not None:
            payload["text"] = self.text
        if self.data is not None:
            payload["data"] = self.data
        if self.file is not None:
            payload["file"] = self.file
        if self.mime_type is not None:
            payload["mimeType"] = self.mime_type
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Part:
        return cls(
            type=raw.get("type") or raw.get("kind") or "text",
            text=raw.get("text"),
            data=raw.get("data"),
            file=raw.get("file"),
            mime_type=raw.get("mimeType") or raw.get("mime_type"),
        )


@dataclass
class Message:
    role: str  # user | agent
    parts: list[Part]
    message_id: str | None = None
    idempotency_key: str | None = None
    correlation_id: str | None = None
    parent_task_id: str | None = None
    root_task_id: str | None = None
    depth: int = 0
    # Phase 2.1: cross-process governance context carried on the A2A wire.
    caller_agent_id: str | None = None
    target_agent_id: str | None = None
    visited_agents: list[str] = field(default_factory=list)
    governance_policy_id: str | None = None
    deadline: str | None = None  # ISO-8601; absolute, so it survives clock skew
    # Phase 2: async completion webhook for long-running / non-blocking tasks.
    callback_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.message_id:
            payload["messageId"] = self.message_id
        if self.idempotency_key:
            payload["idempotencyKey"] = self.idempotency_key
        if self.correlation_id:
            payload["correlationId"] = self.correlation_id
        if self.parent_task_id:
            payload["parentTaskId"] = self.parent_task_id
        if self.root_task_id:
            payload["rootTaskId"] = self.root_task_id
        if self.depth > 0:
            payload["depth"] = self.depth
        if self.caller_agent_id:
            payload["callerAgentId"] = self.caller_agent_id
        if self.target_agent_id:
            payload["targetAgentId"] = self.target_agent_id
        if self.visited_agents:
            payload["visitedAgents"] = list(self.visited_agents)
        if self.governance_policy_id:
            payload["governancePolicyId"] = self.governance_policy_id
        if self.deadline:
            payload["deadline"] = self.deadline
        if self.callback_url:
            payload["callbackUrl"] = self.callback_url
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Message:
        parts = [Part.from_dict(p) for p in raw.get("parts", [])]
        visited = raw.get("visitedAgents") or raw.get("visited_agents") or []
        if isinstance(visited, str):
            visited = [v for v in visited.split(",") if v]
        return cls(
            role=raw.get("role", "agent"),
            parts=parts,
            message_id=raw.get("messageId") or raw.get("message_id"),
            idempotency_key=raw.get("idempotencyKey") or raw.get("idempotency_key"),
            correlation_id=raw.get("correlationId") or raw.get("correlation_id"),
            parent_task_id=raw.get("parentTaskId") or raw.get("parent_task_id"),
            root_task_id=raw.get("rootTaskId") or raw.get("root_task_id"),
            depth=raw.get("depth", 0),
            caller_agent_id=raw.get("callerAgentId") or raw.get("caller_agent_id"),
            target_agent_id=raw.get("targetAgentId") or raw.get("target_agent_id"),
            visited_agents=list(visited),
            governance_policy_id=raw.get("governancePolicyId") or raw.get("governance_policy_id"),
            deadline=raw.get("deadline"),
            callback_url=raw.get("callbackUrl") or raw.get("callback_url"),
        )


@dataclass
class Artifact:
    name: str | None
    parts: list[Part]
    artifact_id: str | None = None
    description: str | None = None

    def text(self) -> str:
        chunks = [p.text for p in self.parts if p.type == "text" and p.text]
        return "\n".join(chunks)

    def data(self) -> dict[str, Any] | None:
        for p in self.parts:
            if p.type == "data" and p.data is not None:
                return p.data
        return None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Artifact:
        return cls(
            name=raw.get("name"),
            parts=[Part.from_dict(p) for p in raw.get("parts", [])],
            artifact_id=raw.get("artifactId") or raw.get("artifact_id"),
            description=raw.get("description"),
        )


@dataclass
class Task:
    id: str
    status: TaskStatus
    artifacts: list[Artifact] = field(default_factory=list)
    history: list[Message] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    parent_task_id: str | None = None
    root_task_id: str | None = None
    correlation_id: str | None = None
    caller_agent_id: str | None = None
    target_agent_id: str | None = None
    depth: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Task:
        # Simplified status parsing - directly use the status value
        status_raw = raw.get("status", "submitted")
        if isinstance(status_raw, dict):
            status_value = status_raw.get("state", "submitted")
        else:
            status_value = str(status_raw)
        try:
            status = TaskStatus(status_value)
        except ValueError:
            status = TaskStatus.WORKING

        artifacts = [Artifact.from_dict(a) for a in raw.get("artifacts", [])]
        history = [Message.from_dict(m) for m in raw.get("history", [])]
        error = None
        if isinstance(status_raw, dict):
            msg = status_raw.get("message")
            if isinstance(msg, dict):
                parts = msg.get("parts") or []
                texts = [p.get("text") for p in parts if p.get("text")]
                error = "\n".join(texts) if texts else None

        return cls(
            id=str(raw.get("id") or raw.get("taskId") or ""),
            status=status,
            artifacts=artifacts,
            history=history,
            metadata=raw.get("metadata") or {},
            error=error,
            parent_task_id=raw.get("parentTaskId") or raw.get("parent_task_id"),
            root_task_id=raw.get("rootTaskId") or raw.get("root_task_id"),
            correlation_id=raw.get("correlationId") or raw.get("correlation_id"),
            caller_agent_id=raw.get("callerAgentId") or raw.get("caller_agent_id"),
            target_agent_id=raw.get("targetAgentId") or raw.get("target_agent_id"),
            depth=raw.get("depth", 0),
        )
