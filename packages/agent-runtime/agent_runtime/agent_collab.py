"""A2A OS — shared, ready-to-use client half for any Agent.

Where :mod:`agent_runtime.collaboration` is the low-level primitive, this module
is the batteries-included helper an Agent drops into its JSON-RPC handler to
become a first-class citizen (Server *and* Client) with one object:

    collab = AgentCollaborator(agent_id="claude-coder", delegate_skill="code-assist")
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

import logging
import os
import threading
from typing import Any, Optional

from .collaboration import A2ACollaborationRuntime, CallContext, GovernanceConfig
from .a2a_server import (  # re-export
    cancel_task as _cancel_task,
    extract_lineage,
    handle_control_method,
    inbound_context,
    notify_callback,
)

logger = logging.getLogger(__name__)


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
        self._heartbeat_stop: Optional[threading.Event] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._active_tasks = 0
        self._active_lock = threading.Lock()

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

    def spawn(
        self,
        goal: str,
        ctx: Optional[CallContext],
        *,
        skill: Optional[str] = None,
        agent_key: Optional[str] = None,
        callback_url: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Fire-and-forget peer spawn; return handles for a later ``join``.

        Returns ``None`` (never raises) when disabled or the call fails.
        """
        target_skill = skill or agent_key or self.delegate_skill
        if not self.enabled() or ctx is None:
            return None
        if not target_skill and not agent_key:
            return None
        runtime = self.runtime()
        if runtime is None:
            return None
        try:
            result = runtime.spawn(
                goal,
                context=ctx,
                skill=skill or (None if agent_key else target_skill),
                agent_key=agent_key,
                required_skills=[target_skill] if target_skill else None,
                callback_url=callback_url,
            )
            task_id = runtime._extract_task_id(result.task)
            return {
                "task_id": task_id,
                "endpoint": result.target_endpoint,
                "target_agent_id": result.target_agent_id,
                "skill": result.skill,
                "status": runtime._extract_status(result.task),
                "correlation_id": result.correlation_id,
                "root_task_id": result.root_task_id,
                "parent_task_id": result.parent_task_id,
                "depth": result.depth,
            }
        except Exception as exc:  # noqa: BLE001
            print(f"[{self.agent_id}] async spawn skipped: {exc}")
            return None

    def join(
        self,
        endpoint: str,
        task_id: str,
        *,
        timeout_s: float = 120.0,
        poll_interval_s: float = 0.5,
    ) -> Any:
        """Poll a peer task until terminal; ``None`` on timeout/failure."""
        runtime = self.runtime()
        if runtime is None:
            # Allow join without OS when endpoint is known: bare A2A client.
            try:
                from a2a_sdk import A2AClient
                import time

                client = A2AClient(endpoint, timeout=min(60.0, float(timeout_s)))
                deadline = time.monotonic() + max(0.1, float(timeout_s))
                terminal = {"completed", "failed", "canceled", "cancelled", "input-required"}
                last = None
                while time.monotonic() < deadline:
                    last = client.get_task(task_id)
                    status = getattr(last, "status", None)
                    state = str(getattr(status, "value", status) or "").lower()
                    if state in terminal:
                        return last
                    time.sleep(poll_interval_s)
                return None
            except Exception as exc:  # noqa: BLE001
                print(f"[{self.agent_id}] join failed: {exc}")
                return None
        try:
            return runtime.join(
                endpoint,
                task_id,
                timeout_s=timeout_s,
                poll_interval_s=poll_interval_s,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[{self.agent_id}] join failed: {exc}")
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
        # Fallback: status message text (working/completed previews)
        status = getattr(task, "status", None)
        if status is None and isinstance(task, dict):
            status = task.get("status")
        if isinstance(status, dict):
            msg = status.get("message") or {}
            parts = msg.get("parts") if isinstance(msg, dict) else None
            for p in parts or []:
                if isinstance(p, dict) and p.get("type") == "text" and p.get("text"):
                    return str(p["text"])
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

    # ── lifecycle heartbeat ──────────────────────────────────────────────

    def set_active_tasks(self, count: int) -> None:
        with self._active_lock:
            self._active_tasks = max(0, int(count))

    def bump_active(self, delta: int = 1) -> None:
        with self._active_lock:
            self._active_tasks = max(0, self._active_tasks + int(delta))

    def heartbeat_once(
        self,
        *,
        active_tasks: Optional[int] = None,
        load: float = 0.0,
        version: Optional[str] = None,
        capabilities: Optional[dict[str, Any]] = None,
        timeout: float = 5.0,
    ) -> bool:
        """POST ``/v1/agent-runtime/{id}/heartbeat``. Returns True on success."""
        if not self.available:
            return False
        with self._active_lock:
            n = self._active_tasks if active_tasks is None else int(active_tasks)
        body: dict[str, Any] = {
            "active_tasks": n,
            "load": float(load),
        }
        if version:
            body["version"] = version
        if capabilities:
            body["capabilities"] = capabilities
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
            headers["X-API-Key"] = self.api_key
        url = f"{self.os_url}/v1/agent-runtime/{self.agent_id}/heartbeat"
        try:
            import httpx

            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=body, headers=headers)
                if resp.status_code >= 400:
                    # Fallback path used by some gateways
                    alt = f"{self.os_url}/v1/agents/{self.agent_id}/heartbeat"
                    resp = client.post(alt, json=body, headers=headers)
                return resp.status_code < 400
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s] heartbeat failed: %s", self.agent_id, exc)
            return False

    def start_heartbeat(
        self,
        *,
        interval_s: float = 15.0,
        version: Optional[str] = None,
        capabilities: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Background heartbeat loop. No-op (returns False) without OS URL."""
        if not self.available:
            return False
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return True
        stop = threading.Event()
        self._heartbeat_stop = stop

        def _loop() -> None:
            while not stop.wait(max(1.0, float(interval_s))):
                self.heartbeat_once(version=version, capabilities=capabilities)

        t = threading.Thread(
            target=_loop,
            name=f"a2a-heartbeat-{self.agent_id}",
            daemon=True,
        )
        self._heartbeat_thread = t
        t.start()
        # Immediate first beat so registry does not mark us stale before interval.
        self.heartbeat_once(version=version, capabilities=capabilities)
        return True

    def stop_heartbeat(self) -> None:
        if self._heartbeat_stop is not None:
            self._heartbeat_stop.set()
        self._heartbeat_stop = None
        self._heartbeat_thread = None


__all__ = ["AgentCollaborator", "inbound_context"]
