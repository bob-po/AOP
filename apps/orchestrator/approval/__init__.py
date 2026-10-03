"""Approval gates: none | system | agent | both.

Plan-time ``requires_approval`` stays the operator (Inbox) gate.
Agents may also emit a runtime HITL signal when they delegate, which
routes to a named peer agent instead of — or in addition to — Inbox.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MODES = frozenset({"none", "system", "agent", "both"})

_SYSTEM_ALIASES = frozenset({"system", "human", "operator", "user", "inbox", "console"})
_AGENT_ALIASES = frozenset({"agent", "peer", "a2a", "agent_only"})
_BOTH_ALIASES = frozenset({"both", "all", "dual", "system+agent", "system_and_agent"})
_NONE_ALIASES = frozenset({"none", "off", "false", "no", "0", ""})


def normalize_mode(raw: Any) -> str:
    if raw is True:
        return "system"
    if raw is False or raw is None:
        return "none"
    s = str(raw).strip().lower().replace(" ", "_")
    if s in _NONE_ALIASES:
        return "none"
    if s in _SYSTEM_ALIASES:
        return "system"
    if s in _AGENT_ALIASES:
        return "agent"
    if s in _BOTH_ALIASES:
        return "both"
    if s in MODES:
        return s
    return "none"


@dataclass(frozen=True)
class ApprovalPolicy:
    mode: str = "none"
    approver_agent: str | None = None
    reason: str | None = None
    system_approved: bool = False
    agent_approved: bool = False

    @property
    def needs_system(self) -> bool:
        return self.mode in {"system", "both"} and not self.system_approved

    @property
    def needs_agent(self) -> bool:
        return self.mode in {"agent", "both"} and not self.agent_approved

    @property
    def needs_gate(self) -> bool:
        return self.needs_system or self.needs_agent

    def wait_status(self) -> str:
        if self.needs_system:
            return "waiting_for_user"
        if self.needs_agent:
            return "waiting_for_agent"
        return "success"

    def to_hitl(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": self.mode,
            "system_approved": bool(self.system_approved),
            "agent_approved": bool(self.agent_approved),
        }
        if self.approver_agent:
            payload["approver_agent"] = self.approver_agent
        if self.reason:
            payload["reason"] = self.reason
        return payload


def policy_from_plan_node(node: Any | None) -> ApprovalPolicy:
    if node is None:
        return ApprovalPolicy()
    if hasattr(node, "to_dict"):
        raw = node.to_dict()
    elif isinstance(node, dict):
        raw = node
    else:
        raw = {
            "requires_approval": bool(getattr(node, "requires_approval", False)),
            "approval_mode": getattr(node, "approval_mode", None),
            "approver_agent": getattr(node, "approver_agent", None),
        }
    mode = normalize_mode(raw.get("approval_mode"))
    if mode == "none" and raw.get("requires_approval"):
        mode = "system"
    approver = raw.get("approver_agent") or raw.get("approver_agent_key")
    approver_s = str(approver).strip() if approver else None
    if mode == "agent" and not approver_s:
        # Unroutable peer gate — fall back so the run does not stall silently.
        mode = "system"
    return ApprovalPolicy(mode=mode, approver_agent=approver_s or None)


def parse_runtime_signal(output: dict[str, Any] | None) -> ApprovalPolicy:
    if not isinstance(output, dict):
        return ApprovalPolicy()
    hitl = output.get("hitl") if isinstance(output.get("hitl"), dict) else None
    if not hitl:
        return ApprovalPolicy()
    mode = normalize_mode(hitl.get("mode") or hitl.get("approval_mode"))
    approver = hitl.get("approver_agent") or hitl.get("approver_agent_key")
    approver_s = str(approver).strip() if approver else None
    if mode == "none" and (hitl.get("requires_approval") or approver_s):
        mode = "agent" if approver_s else "system"
    reason = hitl.get("reason") or hitl.get("message")
    return ApprovalPolicy(
        mode=mode,
        approver_agent=approver_s or None,
        reason=str(reason).strip() if reason else None,
        system_approved=bool(hitl.get("system_approved")),
        agent_approved=bool(hitl.get("agent_approved")),
    )


def combine(plan: ApprovalPolicy, runtime: ApprovalPolicy) -> ApprovalPolicy:
    """Union of plan-time and agent-declared gates (more gates, never fewer)."""
    need_sys = plan.mode in {"system", "both"} or runtime.mode in {"system", "both"}
    need_ag = plan.mode in {"agent", "both"} or runtime.mode in {"agent", "both"}
    if need_sys and need_ag:
        mode = "both"
    elif need_sys:
        mode = "system"
    elif need_ag:
        mode = "agent"
    else:
        mode = "none"
    approver = runtime.approver_agent or plan.approver_agent
    if mode in {"agent", "both"} and not approver:
        # Peer gate without a target → operator Inbox instead of a black hole.
        mode = "both" if need_sys else "system"
    return ApprovalPolicy(
        mode=mode,
        approver_agent=approver,
        reason=runtime.reason or plan.reason,
        system_approved=bool(plan.system_approved or runtime.system_approved),
        agent_approved=bool(plan.agent_approved or runtime.agent_approved),
    )


def resolve_for_node(*, plan_node: Any | None, output: dict[str, Any] | None) -> ApprovalPolicy:
    return combine(policy_from_plan_node(plan_node), parse_runtime_signal(output))


def apply_decision(
    policy: ApprovalPolicy,
    *,
    actor: str,
    approved: bool,
) -> ApprovalPolicy:
    who = str(actor or "system").strip().lower()
    if who in _AGENT_ALIASES:
        who = "agent"
    else:
        who = "system"
    if not approved:
        return policy
    return ApprovalPolicy(
        mode=policy.mode,
        approver_agent=policy.approver_agent,
        reason=policy.reason,
        system_approved=policy.system_approved or who == "system",
        agent_approved=policy.agent_approved or who == "agent",
    )
