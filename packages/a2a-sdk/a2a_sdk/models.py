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

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
        }
        if self.message_id:
            payload["messageId"] = self.message_id
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Message:
        parts = [Part.from_dict(p) for p in raw.get("parts", [])]
        return cls(
            role=raw.get("role", "agent"),
            parts=parts,
            message_id=raw.get("messageId") or raw.get("message_id"),
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

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Task:
        status_raw = raw.get("status", {})
        if isinstance(status_raw, dict):
            state = status_raw.get("state", "submitted")
        else:
            state = str(status_raw)
        try:
            status = TaskStatus(state)
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
        )
