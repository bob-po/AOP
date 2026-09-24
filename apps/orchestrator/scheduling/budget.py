"""Phase 5.10 — Budget check / update (wraps Governance units + Quota USD)."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from scheduling.context import DEFAULT_TENANT_ID, TenantContext, get_tenant_context


@dataclass
class Budget:
    tenant_id: str = DEFAULT_TENANT_ID
    project_id: Optional[str] = None
    scope: str = "tenant"  # tenant | project | task | day | month
    scope_key: str = ""
    currency: str = "USD"
    limit_amount: float = 100.0
    spent_amount: float = 0.0
    soft_limit: bool = False
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def remaining(self) -> float:
        return max(0.0, float(self.limit_amount) - float(self.spent_amount))


class BudgetService:
    """In-memory budgets for hermetic tests; optional PG later."""

    def __init__(self):
        self._lock = threading.RLock()
        self._budgets: dict[tuple[str, str, str], Budget] = {}

    def upsert(self, budget: Budget) -> Budget:
        key = (budget.tenant_id, budget.scope, budget.scope_key)
        with self._lock:
            self._budgets[key] = budget
            return budget

    def get(
        self,
        tenant_id: str,
        *,
        scope: str = "tenant",
        scope_key: str = "",
    ) -> Optional[Budget]:
        with self._lock:
            return self._budgets.get((tenant_id, scope, scope_key))

    def ensure_tenant_budget(
        self, tenant_id: str, *, daily: float = 100.0, monthly: float = 2000.0
    ) -> dict[str, Budget]:
        day = self.get(tenant_id, scope="day") or Budget(
            tenant_id=tenant_id, scope="day", limit_amount=daily
        )
        month = self.get(tenant_id, scope="month") or Budget(
            tenant_id=tenant_id, scope="month", limit_amount=monthly
        )
        self.upsert(day)
        self.upsert(month)
        return {"day": day, "month": month}

    def check(
        self,
        estimated_cost: float,
        *,
        ctx: TenantContext | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        ctx = ctx or get_tenant_context()
        tid = ctx.tenant_id or DEFAULT_TENANT_ID
        self.ensure_tenant_budget(tid)
        violations = []
        with self._lock:
            for scope, key in (
                ("tenant", ""),
                ("day", ""),
                ("month", ""),
                ("task", task_id or ""),
            ):
                if scope == "task" and not task_id:
                    continue
                b = self._budgets.get((tid, scope, key if scope == "task" else ""))
                if not b or not b.enabled:
                    continue
                if b.spent_amount + estimated_cost > b.limit_amount:
                    violations.append(
                        {
                            "scope": scope,
                            "limit": b.limit_amount,
                            "spent": b.spent_amount,
                            "estimated": estimated_cost,
                            "soft": b.soft_limit,
                        }
                    )
        if not violations:
            return {"allowed": True, "estimated_cost": estimated_cost}
        hard = [v for v in violations if not v["soft"]]
        if hard:
            return {
                "allowed": False,
                "action": "REJECT",
                "estimated_cost": estimated_cost,
                "violations": violations,
            }
        return {
            "allowed": True,
            "action": "SOFT_WARN",
            "estimated_cost": estimated_cost,
            "violations": violations,
        }

    def record_spend(self, amount: float, *, tenant_id: str, task_id: str | None = None) -> None:
        with self._lock:
            for scope, key in (("tenant", ""), ("day", ""), ("month", ""), ("task", task_id or "")):
                if scope == "task" and not task_id:
                    continue
                b = self._budgets.get((tenant_id, scope, key if scope == "task" else ""))
                if b and b.enabled:
                    b.spent_amount = float(b.spent_amount) + float(amount)


__all__ = ["Budget", "BudgetService"]
