"""AOP A2A SDK — Agent Card discovery + message/send client.

Protocol baseline: A2A-compatible subset (Agent Card well-known + JSON-RPC).
Internal DTOs stay stable; wire format lives in this package only.
"""

from .card import AgentCard, AgentSkill, fetch_agent_card
from .client import A2AClient, A2AError
from .models import Artifact, Message, Part, Task, TaskStatus

__all__ = [
    "A2AClient",
    "A2AError",
    "AgentCard",
    "AgentSkill",
    "Artifact",
    "Message",
    "Part",
    "Task",
    "TaskStatus",
    "fetch_agent_card",
    "stream_tasks",
    "cancel_task",
    "delegate_task",
]

__version__ = "0.1.0"
