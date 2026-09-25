"""Harness runner protocol — execution kernel behind the A2A shell.

A2A OS owns collaboration (routing, scoring, lineage). Harness runners own
*how* a task is completed (Claude CLI, Pi, DeepSeek tool-loop, …).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional, Protocol, runtime_checkable


SCHEMA_VERSION = "1.0"


class HarnessStatus(str, Enum):
    OK = "ok"
    FAILED = "failed"
    CANCELED = "canceled"
    TIMEOUT = "timeout"


class HarnessEventType(str, Enum):
    STATUS = "status"
    DELTA = "delta"
    TOOL = "tool"
    USAGE = "usage"
    ERROR = "error"
    FINAL = "final"


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    model: Optional[str] = None
    wall_time_ms: int = 0
    estimated_cost: float = 0.0
    currency: str = "USD"

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": int(self.input_tokens or 0),
            "output_tokens": int(self.output_tokens or 0),
            "model": self.model,
            "wall_time_ms": int(self.wall_time_ms or 0),
            "estimated_cost": float(self.estimated_cost or 0.0),
            "currency": self.currency or "USD",
        }


@dataclass
class HarnessEvent:
    """Streaming event from a harness runner.

    When bridged to OS ``ExecutionEvent``, use field name ``timestamp`` and put
    ordering under ``payload.sequence`` (never ``ts``).
    """

    type: HarnessEventType
    task_id: str
    timestamp: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type.value if isinstance(self.type, HarnessEventType) else str(self.type),
            "task_id": self.task_id,
            "timestamp": self.timestamp,
            "payload": dict(self.payload or {}),
        }


@dataclass
class HarnessResult:
    """Normalized harness output — always maps to summary + result artifacts."""

    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    usage: TokenUsage = field(default_factory=TokenUsage)
    status: HarnessStatus = HarnessStatus.OK
    error: Optional[str] = None
    skill_id: str = ""

    def to_data_part(self) -> dict[str, Any]:
        body = {
            "skillId": self.skill_id,
            "schemaVersion": SCHEMA_VERSION,
            "status": self.status.value if isinstance(self.status, HarnessStatus) else str(self.status),
            **dict(self.data or {}),
        }
        if self.error:
            body["error"] = self.error
        body["usage"] = self.usage.to_dict()
        return body


EventCallback = Callable[[HarnessEvent], Awaitable[None] | None]


@runtime_checkable
class HarnessRunner(Protocol):
    """Execution kernel: turn an A2A message into a structured result."""

    async def run(
        self,
        *,
        task_id: str,
        message: dict[str, Any],
        skill_id: str,
        on_event: EventCallback,
    ) -> HarnessResult: ...

    async def cancel(self, task_id: str) -> bool: ...


__all__ = [
    "SCHEMA_VERSION",
    "HarnessStatus",
    "HarnessEventType",
    "TokenUsage",
    "HarnessEvent",
    "HarnessResult",
    "EventCallback",
    "HarnessRunner",
]
