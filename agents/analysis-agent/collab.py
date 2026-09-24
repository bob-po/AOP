"""A2A OS client half of the Analysis Agent.

Makes this Agent a first-class citizen: it can autonomously discover a peer
(e.g. a RAG/knowledge Agent) through the A2A OS and delegate a grounding query
to it — without a central orchestrator pre-wiring the step.

Everything here is best-effort and degrades to a no-op when the OS or the
agent-runtime package is unavailable, so the Agent still works standalone.
"""

from __future__ import annotations

import os
from typing import Any, Optional

try:
    from agent_runtime.collaboration import (
        A2ACollaborationRuntime,
        CallContext,
        GovernanceConfig,
    )
    from agent_runtime.a2a_server import inbound_context  # noqa: F401
    COLLAB_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on installed agent-runtime
    COLLAB_AVAILABLE = False

AGENT_ID = os.getenv("ANALYSIS_AGENT_ID", "analysis-agent")
KNOWLEDGE_SKILL = os.getenv("ANALYSIS_KNOWLEDGE_SKILL", "knowledge-search")

_runtime: Optional[Any] = None


def _os_url() -> Optional[str]:
    return os.getenv("A2A_OS_URL") or os.getenv("GATEWAY_URL")


def autonomous_enabled() -> bool:
    """Autonomous delegation is opt-in via the OS URL (or explicit flag)."""
    flag = os.getenv("ANALYSIS_AUTONOMOUS_RAG", "").lower()
    if flag in {"0", "false", "off", "no"}:
        return False
    if flag in {"1", "true", "on", "yes"}:
        return True
    return bool(_os_url())


def get_runtime() -> Optional[Any]:
    global _runtime
    if not COLLAB_AVAILABLE or not _os_url():
        return None
    if _runtime is None:
        _runtime = A2ACollaborationRuntime(
            agent_id=AGENT_ID,
            os_base_url=_os_url(),
            governance=GovernanceConfig(
                max_delegation_depth=int(os.getenv("A2A_MAX_DEPTH", "5")),
            ),
            api_key=os.getenv("A2A_OS_API_KEY"),
        )
    return _runtime


def fetch_knowledge(goal: str, ctx: Any) -> Optional[str]:
    """Autonomously discover a knowledge Agent and delegate a grounding query.

    Returns the peer's text answer, or None if collaboration is disabled,
    unavailable, or the call fails. Never raises.
    """
    if not autonomous_enabled():
        return None
    runtime = get_runtime()
    if runtime is None:
        return None
    try:
        result = runtime.delegate(
            goal,
            context=ctx,
            skill=KNOWLEDGE_SKILL,
            required_skills=[KNOWLEDGE_SKILL],
        )
        task = result.task
        # Extract the first text artifact from the returned task.
        artifacts = getattr(task, "artifacts", None)
        if artifacts is None and isinstance(task, dict):
            artifacts = task.get("artifacts") or []
        for a in artifacts or []:
            parts = getattr(a, "parts", None)
            if parts is None and isinstance(a, dict):
                parts = a.get("parts") or []
            for p in parts or []:
                ptype = getattr(p, "type", None) or (p.get("type") if isinstance(p, dict) else None)
                ptext = getattr(p, "text", None) or (p.get("text") if isinstance(p, dict) else None)
                if ptype == "text" and ptext:
                    return str(ptext)
        return None
    except Exception as exc:  # noqa: BLE001 - collaboration must never break analysis
        print(f"[Analysis Agent] autonomous delegation skipped: {exc}")
        return None


__all__ = [
    "AGENT_ID",
    "COLLAB_AVAILABLE",
    "autonomous_enabled",
    "fetch_knowledge",
    "get_runtime",
]
