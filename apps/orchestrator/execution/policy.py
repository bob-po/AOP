"""Phase 3 — lightweight policy engine over governance defaults."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class CollaborationPolicy:
    max_agent_visits: int = 3
    max_depth: int = 16
    max_concurrency: int = 8
    timeout_seconds: int = 300
    delegation_timeout_seconds: int = 120
    agent_timeout_seconds: int = 60
    max_retries: int = 3
    capacity_overflow: str = "reject"  # reject | wait
    allowed_agents: list[str] = field(default_factory=list)
    denied_agents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_sources(
        cls,
        *,
        defaults: Optional["CollaborationPolicy"] = None,
        governance_policy: Any = None,
        overrides: Optional[dict[str, Any]] = None,
    ) -> "CollaborationPolicy":
        """Merge priority: overrides > governance row > defaults."""
        base = defaults or cls()
        data = base.to_dict()
        if governance_policy is not None:
            mapping = {
                "max_agent_visits": "max_agent_visits",
                "max_delegation_depth": "max_depth",
                "max_agent_concurrency": "max_concurrency",
                "max_retries": "max_retries",
                "task_timeout_s": "timeout_seconds",
                "delegation_timeout_s": "delegation_timeout_seconds",
                "agent_timeout_s": "agent_timeout_seconds",
                "capacity_overflow": "capacity_overflow",
                "allowed_agents": "allowed_agents",
                "denied_agents": "denied_agents",
            }
            src = (
                governance_policy
                if isinstance(governance_policy, dict)
                else getattr(governance_policy, "__dict__", {})
            )
            for src_k, dst_k in mapping.items():
                val = src.get(src_k) if isinstance(src, dict) else getattr(governance_policy, src_k, None)
                if val is not None:
                    data[dst_k] = val
        if overrides:
            for k, v in overrides.items():
                if k in data and v is not None:
                    data[k] = v
        return cls(**data)

    def allows_agent(self, agent_id: str) -> tuple[bool, str]:
        if self.denied_agents and agent_id in self.denied_agents:
            return False, "denied_agents"
        if self.allowed_agents and agent_id not in self.allowed_agents:
            return False, "not_in_allowed_agents"
        return True, "ok"


class PolicyEngine:
    def __init__(self, default: CollaborationPolicy | None = None):
        self.default = default or CollaborationPolicy()

    def resolve(
        self,
        *,
        governance_policy: Any = None,
        overrides: dict[str, Any] | None = None,
    ) -> CollaborationPolicy:
        return CollaborationPolicy.from_sources(
            defaults=self.default,
            governance_policy=governance_policy,
            overrides=overrides,
        )


__all__ = ["CollaborationPolicy", "PolicyEngine"]
