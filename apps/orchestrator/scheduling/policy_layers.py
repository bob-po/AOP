"""Phase 5.9 — Policy-as-Code layers (extends CollaborationPolicy, no second engine)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from execution.policy import CollaborationPolicy, PolicyEngine


@dataclass
class SchedulingPolicyDoc:
    """Declarative scheduling / resource / retry / cost policy document."""

    max_cost: float | None = None
    max_latency_ms: int | None = None
    require_gpu: bool = False
    require_streaming: bool = False
    max_attempts: int = 3
    allow_agent_reselection: bool = True
    max_concurrency: int = 10
    capacity_overflow: str = "wait"  # reject | wait
    tenant_weight: float = 1.0
    priority: str = "NORMAL"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        extra = d.pop("extra", {}) or {}
        d.update(extra)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "SchedulingPolicyDoc":
        data = dict(data or {})
        known = {
            "max_cost",
            "max_latency_ms",
            "require_gpu",
            "require_streaming",
            "max_attempts",
            "allow_agent_reselection",
            "max_concurrency",
            "capacity_overflow",
            "tenant_weight",
            "priority",
        }
        kwargs = {k: data[k] for k in known if k in data}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(**kwargs, extra=extra)


def merge_policies(
    *layers: SchedulingPolicyDoc | dict[str, Any] | None,
) -> SchedulingPolicyDoc:
    """Later layers override earlier; used as Global → Tenant → Project → Task."""
    merged: dict[str, Any] = {}
    for layer in layers:
        if layer is None:
            continue
        data = layer.to_dict() if isinstance(layer, SchedulingPolicyDoc) else dict(layer)
        for k, v in data.items():
            if v is not None:
                merged[k] = v
    return SchedulingPolicyDoc.from_dict(merged)


class LayeredPolicyEngine:
    """Wraps Phase 3 PolicyEngine; adds scheduling document merge."""

    def __init__(self, base: PolicyEngine | None = None):
        self.base = base or PolicyEngine()
        self._tenant_docs: dict[str, SchedulingPolicyDoc] = {}
        self.global_doc = SchedulingPolicyDoc()

    def set_tenant_policy(self, tenant_id: str, doc: SchedulingPolicyDoc | dict[str, Any]) -> SchedulingPolicyDoc:
        d = doc if isinstance(doc, SchedulingPolicyDoc) else SchedulingPolicyDoc.from_dict(doc)
        self._tenant_docs[tenant_id] = d
        return d

    def get_tenant_policy(self, tenant_id: str) -> SchedulingPolicyDoc:
        return self._tenant_docs.get(tenant_id) or SchedulingPolicyDoc()

    def resolve(
        self,
        *,
        tenant_id: str | None = None,
        project_doc: dict[str, Any] | None = None,
        task_doc: dict[str, Any] | None = None,
        governance_policy: Any = None,
    ) -> tuple[SchedulingPolicyDoc, CollaborationPolicy]:
        tenant_doc = self.get_tenant_policy(tenant_id) if tenant_id else SchedulingPolicyDoc()
        sched = merge_policies(self.global_doc, tenant_doc, project_doc, task_doc)
        collab = self.base.resolve(
            governance_policy=governance_policy,
            overrides={
                "max_concurrency": sched.max_concurrency,
                "max_retries": sched.max_attempts,
                "capacity_overflow": sched.capacity_overflow,
            },
        )
        return sched, collab


__all__ = [
    "SchedulingPolicyDoc",
    "merge_policies",
    "LayeredPolicyEngine",
]
