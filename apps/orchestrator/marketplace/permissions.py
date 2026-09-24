"""Phase 6 Agent Permission — integrate with Tenant/Governance."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from marketplace.manifest import ALLOWED_PERMISSIONS

# Default deny-all except network for published agents
DEFAULT_TENANT_ALLOW = frozenset({"network", "other_agents", "gpu"})


@dataclass
class PermissionDecision:
    allowed: bool
    granted: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    reason: str = ""


class PermissionService:
    """Validate and enforce agent permission declarations."""

    def __init__(self, *, tenant_policy: dict[str, set[str]] | None = None):
        # tenant_id -> allowed permission set
        self._tenant_policy = tenant_policy or {}
        self._agent_grants: dict[str, set[str]] = {}  # "tenant:agent_key" -> granted

    def validate_declared(self, permissions: list[str]) -> PermissionDecision:
        bad = [p for p in permissions if p not in ALLOWED_PERMISSIONS]
        if bad:
            return PermissionDecision(False, denied=bad, reason=f"illegal permissions: {bad}")
        return PermissionDecision(True, granted=list(permissions))

    def tenant_allows(self, tenant_id: str, permissions: list[str]) -> PermissionDecision:
        allow = self._tenant_policy.get(tenant_id, set(DEFAULT_TENANT_ALLOW))
        granted = [p for p in permissions if p in allow]
        denied = [p for p in permissions if p not in allow]
        if denied:
            return PermissionDecision(False, granted=granted, denied=denied, reason="tenant policy deny")
        return PermissionDecision(True, granted=granted)

    def grant(self, tenant_id: str, agent_key: str, permissions: list[str]) -> None:
        key = f"{tenant_id}:{agent_key}"
        self._agent_grants[key] = set(permissions)

    def check_invocation(
        self,
        tenant_id: str,
        agent_key: str,
        required: list[str],
    ) -> PermissionDecision:
        key = f"{tenant_id}:{agent_key}"
        grants = self._agent_grants.get(key, set())
        missing = [p for p in required if p not in grants]
        if missing:
            return PermissionDecision(False, granted=list(grants), denied=missing, reason="missing grants")
        return PermissionDecision(True, granted=list(grants))

    def from_manifest_permissions(self, raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, dict):
            return [k for k, v in raw.items() if v and k in ALLOWED_PERMISSIONS]
        if isinstance(raw, list):
            return [str(p) for p in raw if str(p) in ALLOWED_PERMISSIONS]
        return []
