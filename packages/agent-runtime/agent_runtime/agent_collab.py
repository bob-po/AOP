"""A2A OS — shared, ready-to-use client half for any Agent.

Where :mod:`agent_runtime.collaboration` is the low-level primitive, this module
is the batteries-included helper an Agent drops into its JSON-RPC handler to
become a first-class citizen (Server *and* Client) with one object:

    collab = AgentCollaborator(agent_id="rag-agent", delegate_skill="business-analysis")
    ...
    ctx = inbound_context(params, agent_id=collab.agent_id, task_id=task_id)
    extra = collab.fetch(goal, ctx)          # autonomous peer delegation
    handled = collab.handle_control(method, params, _TASKS, req_id)

Autonomous delegation is OFF unless the A2A OS URL is configured (or explicitly
enabled), so an Agent behaves exactly as before when running standalone. All
network/delegation failures degrade to ``None`` — collaboration never breaks the
Agent's own task.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from .collaboration import A2ACollaborationRuntime, CallContext, GovernanceConfig
from .a2a_server import (  # re-export
    cancel_task as _cancel_task,
    extract_lineage,
    handle_control_method,
    inbound_context,
    notify_callback,
)


class AgentCollaborator:
    """Per-Agent A2A client facade with safe, env-driven defaults."""

    def __init__(
        self,
        *,
        agent_id: str,
        delegate_skill: Optional[str] = None,
        os_url: Optional[str] = None,
        api_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        max_depth: int = 5,
        runtime: Optional[A2ACollaborationRuntime] = None,
    ):
        self.agent_id = agent_id
        self.delegate_skill = delegate_skill or os.getenv(
            f"{agent_id.upper().replace('-', '_')}_DELEGATE_SKILL"
        )
        self.os_url = (os_url or os.getenv("A2A_OS_URL") or os.getenv("GATEWAY_URL") or "").rstrip("/")
        self.api_key = api_key or os.getenv("A2A_OS_API_KEY")
        self._enabled_override = enabled
        self.max_depth = max_depth
        self._runtime = runtime

    # ── availability / enablement ────────────────────────────────────────

    @property
    def available(self) -> bool:
        return bool(self.os_url)

    def enabled(self) -> bool:
        """Explicit override wins; otherwise auto-enable when an OS is configured."""
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        env = os.getenv("A2A_AUTONOMOUS", "").lower()
        if env in {"0", "false", "off", "no"}:
            return False
        if env in {"1", "true", "on", "yes"}:
            return True
        return self.available

    def runtime(self) -> Optional[A2ACollaborationRuntime]:
        if self._runtime is not None:
            return self._runtime
        if not self.available:
            return None
        self._runtime = A2ACollaborationRuntime(
            agent_id=self.agent_id,
            os_base_url=self.os_url,
            governance=GovernanceConfig(max_delegation_depth=self.max_depth),
            api_key=self.api_key,
        )
        return self._runtime

    # ── autonomous delegation ────────────────────────────────────────────

    def fetch(
        self,
        goal: str,
        ctx: Optional[CallContext],
        *,
        skill: Optional[str] = None,
    ) -> Optional[str]:
        """Discover a peer for ``skill`` and delegate ``goal``; return its text.

        Returns ``None`` (never raises) when disabled, unavailable, no skill is
        configured, or the call fails.
        """
        target_skill = skill or self.delegate_skill
        if not self.enabled() or not target_skill or ctx is None:
            return None
        runtime = self.runtime()
        if runtime is None:
            return None
        try:
            result = runtime.delegate(
                goal,
                context=ctx,
                skill=target_skill,
                required_skills=[target_skill],
            )
            return self.extract_text(result.task)
        except Exception as exc:  # noqa: BLE001 - collaboration must never break the task
            print(f"[{self.agent_id}] autonomous delegation skipped: {exc}")
            return None

    @staticmethod
    def extract_text(task: Any) -> Optional[str]:
        """First text artifact from a Task object or dict."""
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

    # ── server-side helpers ──────────────────────────────────────────────

    def context(self, params: dict[str, Any], *, task_id: Optional[str] = None) -> Optional[CallContext]:
        """Build inbound lineage context for a received message/send."""
        return inbound_context(params, agent_id=self.agent_id, task_id=task_id)

    def cancel(self, tasks_store: dict[str, Any], task_id: Optional[str]):
        """Handle tasks/cancel over a local task store. Returns (ok, task)."""
        return _cancel_task(tasks_store, task_id)

    def handle_control(
        self,
        method: Optional[str],
        params: dict[str, Any],
        tasks_store: dict[str, Any],
        req_id: Any,
        *,
        subscribe_timeout_s: float = 30.0,
    ) -> Optional[dict[str, Any]]:
        """Dispatch ``tasks/get|cancel|subscribe``. Returns JSON-RPC body or None."""
        return handle_control_method(
            method,
            params,
            req_id=req_id,
            tasks=tasks_store,
            subscribe_timeout_s=subscribe_timeout_s,
        )

    def after_complete(self, params: dict[str, Any], task: dict[str, Any]) -> None:
        """Fire optional ``callbackUrl`` after a task reaches a terminal state."""
        lin = extract_lineage(params)
        notify_callback(lin.get("callback_url"), task)


__all__ = ["AgentCollaborator", "inbound_context"]
