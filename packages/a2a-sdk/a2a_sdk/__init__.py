"""AOP A2A SDK — Agent Card discovery + JSON-RPC client.

Aligned with a2aproject/A2A (see ``a2a_sdk.protocol``). Platform extensions
live under ``metadata``; OS control plane stays on ``/v1/*``.
"""

from .card import AgentCard, AgentSkill, fetch_agent_card
from .client import A2AClient, A2AError, first_data_artifact, first_text_artifact
from .models import Artifact, Message, Part, Task, TaskStatus
from .protocol import PROTOCOL_VERSION, SPEC_COMMIT, SPEC_URL

__all__ = [
    "A2AClient",
    "A2AError",
    "AgentCard",
    "AgentSkill",
    "Artifact",
    "Message",
    "Part",
    "PROTOCOL_VERSION",
    "SPEC_COMMIT",
    "SPEC_URL",
    "Task",
    "TaskStatus",
    "fetch_agent_card",
    "first_data_artifact",
    "first_text_artifact",
]

__version__ = "0.4.0"
