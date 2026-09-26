"""A2A OS — Agent-side collaboration runtime.

This module turns any Agent into a first-class citizen of the A2A network:
a Server *and* a Client. It lets an Agent autonomously

    discover peers  ->  route to the best peer  ->  call/delegate a task

without going through a central orchestrator, while propagating task lineage
(``correlation_id`` / ``root_task_id`` / ``parent_task_id`` / ``depth``) and
enforcing governance so an Agent network cannot recurse out of control.

The OS *governs*; the *Agent decides*. Discovery/routing return candidates and
a suggested selection, but the calling Agent owns the decision of whether and
whom to invoke.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

# Governance error codes (also expected by the OS task runtime).
RECURSION_LIMIT_EXCEEDED = "RECURSION_LIMIT_EXCEEDED"
CYCLE_DETECTED = "CYCLE_DETECTED"
CALL_LIMIT_EXCEEDED = "CALL_LIMIT_EXCEEDED"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"
DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
POLICY_DISABLED = "POLICY_DISABLED"
NO_AGENT_AVAILABLE = "NO_AGENT_AVAILABLE"


class GovernanceError(RuntimeError):
    """Raised when a delegation would violate runtime governance."""

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


@dataclass
class GovernanceConfig:
    """Bounds that keep an autonomous Agent network from running away."""

    max_delegation_depth: int = 5
    max_calls_per_task: int = 20
    # Allow A->B->A (2 visits); block runaway A->B->A->B->A (3rd visit of A/B).
    # Aligned with OS default ``a2a_governance_policies.max_agent_visits``.
    max_agent_visits: int = 3
    detect_cycles: bool = True
    request_timeout: float = 60.0
    # Phase 2.2: consult the trusted OS governance authority (POST
    # /v1/governance/check) before delegating. The OS — not this Agent — is the
    # source of truth for depth/visits/budget/concurrency; the local check below
    # is only a fast pre-filter and a fallback when the OS is unreachable.
    use_os_governance: bool = True


@dataclass
class CallContext:
    """Lineage carried across an A2A call chain.

    ``visited_agents`` is the ordered chain of agent ids that have handled this
    correlation so far; it powers cycle detection without forbidding legitimate
    reverse calls (A -> B -> A).
    """

    correlation_id: str
    caller_agent_id: str
    root_task_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    depth: int = 0
    visited_agents: tuple[str, ...] = ()
    calls_made: int = 0
    # This Agent's own current task id. Used as the parent_task_id of any edge it
    # creates when delegating onward, so the runtime graph nests correctly
    # (caller's task -> callee's task) across a real multi-hop chain.
    self_task_id: Optional[str] = None
    # Phase 2.1: governance context that travels across process boundaries.
    governance_policy_id: Optional[str] = None
    deadline: Optional[str] = None  # ISO-8601 absolute deadline for the whole chain

    def child(self, target_agent_id: str, *, parent_task_id: Optional[str]) -> CallContext:
        return CallContext(
            correlation_id=self.correlation_id,
            caller_agent_id=target_agent_id,
            root_task_id=self.root_task_id,
            parent_task_id=parent_task_id,
            depth=self.depth + 1,
            # Merge rule: a child inherits THIS branch's visit chain and appends
            # the target. Parallel branches each derive from the shared parent
            # context independently, so one branch's visits never leak into
            # another's chain (no cross-branch pollution).
            visited_agents=self.visited_agents + (target_agent_id,),
            calls_made=self.calls_made + 1,
            self_task_id=None,
            governance_policy_id=self.governance_policy_id,
            deadline=self.deadline,
        )

    @classmethod
    def from_inbound(
        cls,
        *,
        agent_id: str,
        correlation_id: str,
        task_id: Optional[str] = None,
        root_task_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        depth: int = 0,
        visited_agents: Optional[list[str]] = None,
        governance_policy_id: Optional[str] = None,
        deadline: Optional[str] = None,
    ) -> CallContext:
        """Build a context for an Agent that just received an inbound task."""
        chain = tuple(visited_agents or ())
        if agent_id and (not chain or chain[-1] != agent_id):
            chain = chain + (agent_id,)
        return cls(
            correlation_id=correlation_id,
            caller_agent_id=agent_id,
            root_task_id=root_task_id or task_id,
            parent_task_id=parent_task_id,
            depth=depth,
            visited_agents=chain,
            self_task_id=task_id,
            governance_policy_id=governance_policy_id,
            deadline=deadline,
        )


@dataclass
class DelegationResult:
    """Outcome of an Agent-initiated A2A call."""

    task: Any
    target_agent_id: str
    target_endpoint: str
    skill: Optional[str]
    depth: int
    correlation_id: str
    root_task_id: Optional[str]
    parent_task_id: Optional[str]
    selection_reason: dict[str, Any] = field(default_factory=dict)


class A2ACollaborationRuntime:
    """Client half of an Agent: discover, route and call other Agents.

    Parameters
    ----------
    agent_id:
        This Agent's identity (used as ``caller_agent_id`` and for cycle checks).
    os_base_url:
        Base URL of the A2A OS (gateway or orchestrator). Used for the open
        ``/v1/discover`` and ``/v1/route`` infrastructure endpoints.
    a2a_client_factory:
        Optional factory ``(endpoint, timeout) -> client`` exposing
        ``send_text(...)``. Injected in tests; defaults to the a2a-sdk client.
    """

    def __init__(
        self,
        *,
        agent_id: str,
        os_base_url: str | None = None,
        governance: GovernanceConfig | None = None,
        api_key: str | None = None,
        http_transport: Optional[httpx.BaseTransport] = None,
        a2a_client_factory: Optional[Callable[[str, float], Any]] = None,
        record_graph: bool = True,
    ):
        self.agent_id = agent_id
        self.os_base_url = (
            os_base_url
            or os.getenv("A2A_OS_URL")
            or os.getenv("GATEWAY_URL")
            or "http://127.0.0.1:8080"
        ).rstrip("/")
        self.governance = governance or GovernanceConfig()
        self.api_key = api_key or os.getenv("A2A_OS_API_KEY")
        self._transport = http_transport
        self._client_factory = a2a_client_factory
        self.record_graph = record_graph

    # ── OS infrastructure calls ──────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.os_base_url}{path}"
        with httpx.Client(
            timeout=self.governance.request_timeout, transport=self._transport
        ) as client:
            resp = client.post(url, json=payload, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _extract_task_id(task: Any) -> Optional[str]:
        if task is None:
            return None
        tid = getattr(task, "id", None)
        if tid is None and isinstance(task, dict):
            tid = task.get("id") or task.get("taskId")
        return str(tid) if tid else None

    @staticmethod
    def _extract_status(task: Any) -> str:
        status = getattr(task, "status", None)
        if status is None and isinstance(task, dict):
            status = task.get("status")
        if isinstance(status, dict):
            return str(status.get("state") or "submitted")
        value = getattr(status, "value", status)
        return str(value) if value else "submitted"

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self.os_base_url}{path}"
        with httpx.Client(
            timeout=self.governance.request_timeout, transport=self._transport
        ) as client:
            resp = client.get(url, headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    def _lookup_agent(self, agent_key: str) -> dict[str, Any] | None:
        """Resolve an agent by key/id via OS list (best-effort)."""
        try:
            data = self._get("/v1/agents")
        except Exception as exc:  # noqa: BLE001
            logger.debug("agent lookup failed: %s", exc)
            return None
        agents = data.get("agents") if isinstance(data, dict) else None
        if not isinstance(agents, list):
            return None
        key = agent_key.strip().lower()
        for a in agents:
            if not isinstance(a, dict):
                continue
            for field in ("agent_key", "agentKey", "agent_id", "agentId", "name", "id"):
                val = str(a.get(field) or "").strip().lower()
                if val and val == key:
                    return a
        return None

    def _record_edge(self, *, child_ctx: CallContext, target_agent_id: str,
                     task_id: Optional[str], skill: Optional[str], status: str) -> None:
        """Best-effort: report this A2A call to the OS runtime graph.

        Failures are swallowed — graph recording must never break a delegation.
        """
        if not self.record_graph:
            return
        try:
            self._post(
                "/v1/runtime/edges",
                {
                    "caller_agent_id": self.agent_id,
                    "target_agent_id": target_agent_id,
                    "root_task_id": child_ctx.root_task_id,
                    "parent_task_id": child_ctx.parent_task_id,
                    "task_id": task_id,
                    "correlation_id": child_ctx.correlation_id,
                    "skill": skill,
                    "depth": child_ctx.depth,
                    "status": status,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("runtime graph record failed: %s", exc)

    def discover(
        self,
        *,
        required_skills: list[str] | None = None,
        capabilities: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        match_all_skills: bool = False,
        exclude_agent_ids: list[str] | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Ask the OS for Agents matching a capability requirement."""
        payload: dict[str, Any] = {
            "required_skills": required_skills or [],
            "capabilities": capabilities or {},
            "match_all_skills": match_all_skills,
            "exclude_agent_ids": exclude_agent_ids or [],
            "limit": limit,
        }
        if input:
            payload["input"] = input
        if output:
            payload["output"] = output
        return self._post("/v1/discover", payload)

    def route(
        self,
        *,
        skill: str | None = None,
        required_skills: list[str] | None = None,
        capabilities: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        exclude_agent_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ask the OS to select the best Agent for a requirement."""
        payload: dict[str, Any] = {
            "required_skills": required_skills or [],
            "capabilities": capabilities or {},
            "exclude_agent_ids": exclude_agent_ids or [],
        }
        if skill:
            payload["skill"] = skill
        if input:
            payload["input"] = input
        if output:
            payload["output"] = output
        return self._post("/v1/route", payload)

    # ── Agent-to-Agent calls ─────────────────────────────────────────────

    def _make_client(self, endpoint: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(endpoint, self.governance.request_timeout)
        from a2a_sdk import A2AClient  # local import: optional at runtime

        return A2AClient(endpoint, timeout=self.governance.request_timeout)

    @staticmethod
    def delegation_idempotency_key(
        *,
        correlation_id: str | None,
        parent_task_id: str | None,
        target_agent_id: str,
        skill: str | None,
        text: str,
    ) -> str:
        """Stable key so retries of the same hop do not double-execute.

        Derived from lineage + target + skill + content hash — never a random
        UUID — so a network retry of the identical delegation hits the callee's
        idempotency cache (and OS request tracking when present).
        """
        digest = hashlib.sha256(
            f"{correlation_id or ''}|{parent_task_id or ''}|"
            f"{target_agent_id}|{skill or ''}|{text}".encode("utf-8")
        ).hexdigest()[:32]
        return f"a2a-del-{digest}"

    def call_agent(
        self,
        endpoint: str,
        text: str,
        *,
        context: CallContext,
        skill_id: str | None = None,
        target_agent_id: str | None = None,
        idempotency_key: str | None = None,
        callback_url: str | None = None,
        async_mode: bool = False,
    ) -> Any:
        """Low-level outbound A2A call with full lineage propagation."""
        client = self._make_client(endpoint)
        key = idempotency_key or self.delegation_idempotency_key(
            correlation_id=context.correlation_id,
            parent_task_id=context.parent_task_id,
            target_agent_id=target_agent_id or "",
            skill=skill_id,
            text=text,
        )
        return client.send_text(
            text,
            skill_id=skill_id,
            idempotency_key=key,
            correlation_id=context.correlation_id,
            parent_task_id=context.parent_task_id,
            root_task_id=context.root_task_id,
            depth=context.depth,
            caller_agent_id=self.agent_id,
            target_agent_id=target_agent_id,
            visited_agents=list(context.visited_agents),
            governance_policy_id=context.governance_policy_id,
            deadline=context.deadline,
            callback_url=callback_url,
            async_mode=async_mode,
        )

    def spawn(
        self,
        text: str,
        *,
        context: CallContext,
        skill: str | None = None,
        agent_key: str | None = None,
        required_skills: list[str] | None = None,
        callback_url: str | None = None,
        self_task_id: str | None = None,
        selection: dict[str, Any] | None = None,
    ) -> DelegationResult:
        """Route to a peer and start work without waiting for completion."""
        route_skill = skill or agent_key
        skills = required_skills or ([route_skill] if route_skill else [])
        if selection is None and agent_key:
            found = self._lookup_agent(agent_key)
            if found and (found.get("endpoint") or found.get("url")):
                selection = {
                    "selected_agent": {
                        "agent_id": found.get("agent_id") or found.get("id"),
                        "agent_key": found.get("agent_key") or agent_key,
                        "endpoint": found.get("endpoint") or found.get("url"),
                        "status": found.get("status"),
                    }
                }
        selection = selection or self.route(
            skill=route_skill,
            required_skills=skills,
            exclude_agent_ids=[self.agent_id] if self.agent_id else None,
        )
        chosen = selection.get("selected_agent") or (
            (selection.get("candidates") or [None])[0]
        )
        if not chosen:
            raise GovernanceError(
                f"no agent available for skills={skills!r} agent_key={agent_key!r}",
                code=NO_AGENT_AVAILABLE,
            )

        target_id = str(
            chosen.get("agent_key")
            or chosen.get("agent_id")
            or chosen.get("agentId")
            or agent_key
            or ""
        )
        endpoint = chosen.get("endpoint") or chosen.get("url") or ""
        if not endpoint:
            raise GovernanceError(
                f"selected agent {target_id!r} has no endpoint", code=NO_AGENT_AVAILABLE
            )

        self._check_governance(context, target_id)
        decision_ctx = self._os_governance_check(context, target_id)

        child_ctx = context.child(
            target_id,
            parent_task_id=self_task_id or context.self_task_id or context.parent_task_id,
        )
        skill_id = skill or route_skill or (skills[0] if skills else None)
        try:
            task = self.call_agent(
                endpoint,
                text,
                context=child_ctx,
                skill_id=skill_id,
                target_agent_id=target_id,
                callback_url=callback_url,
                async_mode=True,
            )
            task_id = self._extract_task_id(task)
            status = self._extract_status(task) or "submitted"
            self._record_edge(
                child_ctx=child_ctx,
                target_agent_id=target_id,
                task_id=task_id,
                skill=skill_id,
                status=status,
            )
            return DelegationResult(
                task=task,
                target_agent_id=target_id,
                target_endpoint=endpoint,
                skill=skill_id,
                depth=child_ctx.depth,
                correlation_id=child_ctx.correlation_id,
                root_task_id=child_ctx.root_task_id,
                parent_task_id=child_ctx.parent_task_id,
                selection_reason={
                    "score": chosen.get("score"),
                    "score_breakdown": chosen.get("score_breakdown"),
                    "status": chosen.get("status"),
                    "async": True,
                },
            )
        finally:
            self._os_governance_release(decision_ctx)

    def join(
        self,
        endpoint: str,
        task_id: str,
        *,
        timeout_s: float = 120.0,
        poll_interval_s: float = 0.5,
    ) -> Any | None:
        """Poll ``tasks/get`` until the peer task reaches a terminal state."""
        import time

        client = self._make_client(endpoint)
        deadline = time.monotonic() + max(0.1, float(timeout_s))
        terminal = {"completed", "failed", "canceled", "cancelled", "input-required"}
        last: Any = None
        while time.monotonic() < deadline:
            try:
                last = client.get_task(task_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("join poll failed task=%s: %s", task_id, exc)
                time.sleep(poll_interval_s)
                continue
            state = self._extract_status(last).lower()
            if state in terminal:
                return last
            time.sleep(poll_interval_s)
        if last is not None and self._extract_status(last).lower() in terminal:
            return last
        return None

    def _check_governance(self, context: CallContext, target_agent_id: str) -> None:
        gov = self.governance
        if context.depth + 1 > gov.max_delegation_depth:
            raise GovernanceError(
                f"delegation depth {context.depth + 1} exceeds max {gov.max_delegation_depth}",
                code=RECURSION_LIMIT_EXCEEDED,
            )
        if context.calls_made + 1 > gov.max_calls_per_task:
            raise GovernanceError(
                f"call count {context.calls_made + 1} exceeds max {gov.max_calls_per_task}",
                code=CALL_LIMIT_EXCEEDED,
            )
        if gov.detect_cycles and target_agent_id:
            visits = context.visited_agents.count(target_agent_id)
            if visits >= gov.max_agent_visits:
                raise GovernanceError(
                    f"agent {target_agent_id!r} already visited {visits} times "
                    f"(max {gov.max_agent_visits}); chain={list(context.visited_agents)}",
                    code=CYCLE_DETECTED,
                )

    def _os_governance_check(
        self, context: CallContext, target_agent_id: str
    ) -> Optional[dict[str, Any]]:
        """Consult the trusted OS governance authority before delegating.

        Returns the decision ``context`` (needed to release in-flight concurrency
        afterwards) or ``None`` when the check is disabled or the OS is
        unreachable. On an authoritative *deny* we raise GovernanceError carrying
        the OS's stable code — the OS decides, the Agent cannot override it.

        A network failure to reach the OS is NOT a governance decision: we
        degrade to the local fast check (already applied) so an OS blip does not
        wedge the whole Agent network, and log it loudly.
        """
        if not self.governance.use_os_governance:
            return None
        # Budget/call counters are keyed by root_task_id; without one the OS
        # cannot reserve atomically — fall back to local depth/visit bounds.
        root = context.root_task_id
        if not root:
            return None
        payload = {
            "root_task_id": root,
            "caller_agent_id": self.agent_id,
            "target_agent_id": target_agent_id,
            "caller_task_id": context.self_task_id,
            "correlation_id": context.correlation_id,
            "deadline": context.deadline,
            "claimed_depth": context.depth,
        }
        try:
            decision = self._post("/v1/governance/check", payload)
        except Exception as exc:  # noqa: BLE001 - OS unreachable: degrade gracefully
            logger.warning(
                "OS governance check unavailable (%s); falling back to local checks", exc
            )
            return None
        if not decision.get("allowed", False):
            code = decision.get("code") or QUOTA_EXCEEDED
            reason = decision.get("reason") or "denied by OS governance"
            raise GovernanceError(f"OS governance denied: {reason}", code=code)
        return decision.get("context") or None

    def _os_governance_release(self, decision_ctx: Optional[dict[str, Any]]) -> None:
        """Release in-flight concurrency reserved by a successful OS check.

        Best-effort: a failure here only means the OS's in-flight counter decays
        on its TTL, never that the delegation itself failed.
        """
        if not decision_ctx:
            return
        try:
            self._post("/v1/governance/release", {"context": decision_ctx})
        except Exception as exc:  # noqa: BLE001
            logger.debug("OS governance release failed: %s", exc)

    def delegate(
        self,
        text: str,
        *,
        context: CallContext,
        skill: str | None = None,
        required_skills: list[str] | None = None,
        capabilities: dict[str, Any] | None = None,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        self_task_id: str | None = None,
        selection: dict[str, Any] | None = None,
    ) -> DelegationResult:
        """Autonomously route to a peer Agent and delegate ``text`` to it.

        Flow: governance check -> OS route -> outbound A2A call. The OS is used
        only as discovery/routing infrastructure; this Agent decides to delegate.
        """
        skills = required_skills or ([skill] if skill else [])
        selection = selection or self.route(
            skill=skill,
            required_skills=skills,
            capabilities=capabilities,
            input=input,
            output=output,
            exclude_agent_ids=[self.agent_id] if self.agent_id else None,
        )
        chosen = selection.get("selected_agent") or (
            (selection.get("candidates") or [None])[0]
        )
        if not chosen:
            raise GovernanceError(
                f"no agent available for skills={skills!r}", code=NO_AGENT_AVAILABLE
            )

        target_id = str(chosen.get("agent_id") or chosen.get("agent_key") or "")
        endpoint = chosen.get("endpoint") or ""
        if not endpoint:
            raise GovernanceError(
                f"selected agent {target_id!r} has no endpoint", code=NO_AGENT_AVAILABLE
            )

        # Local fast pre-filter (depth / visit bound allowing A->B->A), then the
        # authoritative OS check (budget / call quota / concurrency / lineage).
        self._check_governance(context, target_id)
        decision_ctx = self._os_governance_check(context, target_id)

        child_ctx = context.child(
            target_id,
            parent_task_id=self_task_id or context.self_task_id or context.parent_task_id,
        )
        skill_id = skill or (skills[0] if skills else None)
        try:
            task = self.call_agent(
                endpoint,
                text,
                context=child_ctx,
                skill_id=skill_id,
                target_agent_id=target_id,
            )
            task_id = self._extract_task_id(task)
            status = self._extract_status(task)
            self._record_edge(
                child_ctx=child_ctx,
                target_agent_id=target_id,
                task_id=task_id,
                skill=skill_id,
                status=status,
            )
            return DelegationResult(
                task=task,
                target_agent_id=target_id,
                target_endpoint=endpoint,
                skill=skill_id,
                depth=child_ctx.depth,
                correlation_id=child_ctx.correlation_id,
                root_task_id=child_ctx.root_task_id,
                parent_task_id=child_ctx.parent_task_id,
                selection_reason={
                    "score": chosen.get("score"),
                    "score_breakdown": chosen.get("score_breakdown"),
                    "status": chosen.get("status"),
                },
            )
        finally:
            self._os_governance_release(decision_ctx)


__all__ = [
    "A2ACollaborationRuntime",
    "CallContext",
    "DelegationResult",
    "GovernanceConfig",
    "GovernanceError",
    "RECURSION_LIMIT_EXCEEDED",
    "CYCLE_DETECTED",
    "CALL_LIMIT_EXCEEDED",
    "NO_AGENT_AVAILABLE",
]
