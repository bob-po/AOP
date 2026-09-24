"""Phase 5.2 — ResourceQuota façade over existing QuotaService + lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from scheduling.context import DEFAULT_TENANT_ID, TenantContext, get_tenant_context


@dataclass
class ResourceQuota:
    tenant_id: str = DEFAULT_TENANT_ID
    project_id: str = ""
    cpu: float = 32.0
    memory_mb: int = 65536
    gpu: int = 0
    max_concurrency: int = 20
    max_queue_depth: int = 100
    tokens_per_day: int = 1_000_000
    # From legacy QuotaService snapshot when available
    max_tasks_per_day: int = 100
    max_agent_runs_per_day: int = 500
    max_estimated_usd_per_month: float = 100.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResourceService:
    """Unify tenant_quotas + a2a_resource_quotas without a second enforcer."""

    def __init__(self, quota_service: Any | None = None):
        self._quota = quota_service

    def get_quota(
        self,
        *,
        tenant_id: str | None = None,
        project_id: str = "",
        ctx: TenantContext | None = None,
    ) -> ResourceQuota:
        ctx = ctx or get_tenant_context()
        tid = tenant_id or ctx.tenant_id or DEFAULT_TENANT_ID
        rq = ResourceQuota(tenant_id=tid, project_id=project_id or (ctx.project_id or ""))
        # Overlay legacy QuotaService limits when present
        if self._quota is not None:
            try:
                snap = self._quota.snapshot(tid) if hasattr(self._quota, "snapshot") else None
                if not snap and hasattr(self._quota, "get_limits"):
                    snap = self._quota.get_limits(tid)
                if isinstance(snap, dict):
                    for k in (
                        "max_tasks_per_day",
                        "max_agent_runs_per_day",
                        "max_concurrent_tasks",
                        "max_estimated_usd_per_month",
                    ):
                        if k in snap and snap[k] is not None:
                            if k == "max_concurrent_tasks":
                                rq.max_concurrency = int(snap[k])
                            else:
                                setattr(rq, k, type(getattr(rq, k))(snap[k]))
            except Exception:  # noqa: BLE001
                pass
        # Optional DB resource envelope
        try:
            row = self._load_resource_row(tid, rq.project_id)
            if row:
                rq.cpu = float(row.get("cpu") or rq.cpu)
                rq.memory_mb = int(row.get("memory_mb") or rq.memory_mb)
                rq.gpu = int(row.get("gpu") or rq.gpu)
                rq.max_concurrency = int(row.get("max_concurrency") or rq.max_concurrency)
                rq.max_queue_depth = int(row.get("max_queue_depth") or rq.max_queue_depth)
                rq.tokens_per_day = int(row.get("tokens_per_day") or rq.tokens_per_day)
        except Exception:  # noqa: BLE001
            pass
        return rq

    def check_agent_capacity(
        self,
        agent_health: dict[str, Any] | None,
        *,
        queue_depth: int = 0,
        quota: ResourceQuota | None = None,
    ) -> tuple[bool, str]:
        """Resource filter input for Scheduler (does not replace Governance)."""
        if not agent_health:
            return True, "legacy_untracked"
        if agent_health.get("at_capacity"):
            q = quota or self.get_quota()
            if queue_depth >= q.max_queue_depth:
                return False, "queue_full"
            return False, "at_capacity_may_wait"
        return True, "ok"

    def _load_resource_row(self, tenant_id: str, project_id: str) -> Optional[dict[str, Any]]:
        import os

        try:
            from db import connect

            url = os.getenv("DATABASE_URL", "postgresql://aop:aop@127.0.0.1:5432/aop")
            with connect(url) as conn:
                row = conn.execute(
                    """
                    SELECT * FROM a2a_resource_quotas
                     WHERE tenant_id=%s AND project_id=%s
                    """,
                    (tenant_id, project_id or ""),
                ).fetchone()
                if row:
                    return dict(row)
                row = conn.execute(
                    """
                    SELECT * FROM a2a_resource_quotas
                     WHERE tenant_id=%s AND project_id=''
                    """,
                    (tenant_id,),
                ).fetchone()
                return dict(row) if row else None
        except Exception:  # noqa: BLE001
            return None


__all__ = ["ResourceQuota", "ResourceService"]
