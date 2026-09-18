"""Tenant usage quotas (Phase 28).

Enforces daily task / agent-run caps, concurrent running tasks, and
monthly estimated USD (via BillingService) before creating new work.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

from billing import BillingService, DEFAULT_TENANT_ID


class QuotaExceeded(PermissionError):
    """Raised when a tenant would exceed configured quotas."""

    def __init__(self, code: str, message: str, *, snapshot: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.snapshot = snapshot or {}


_DEFAULTS = {
    "max_tasks_per_day": 100,
    "max_agent_runs_per_day": 500,
    "max_concurrent_tasks": 20,
    "max_estimated_usd_per_month": 100.0,
    "enabled": True,
    "plan_tier": "free",
}

_DEFAULT_BOOST = {
    "tasks_per_day_add": 50,
    "runs_per_day_add": 200,
    "concurrent_add": 5,
    "usd_month_add_factor": 10.0,
    "usd_month_add_min": 50.0,
}


def quotas_enabled() -> bool:
    return os.getenv("TENANT_QUOTAS", "1").lower() not in {"0", "false", "no", "off"}


def payment_boost_enabled() -> bool:
    return os.getenv("QUOTA_PAYMENT_BOOST", "1").lower() not in {"0", "false", "no", "off"}


def load_boost_config() -> dict[str, float]:
    raw = os.getenv("QUOTA_BOOST_JSON", "").strip()
    out = dict(_DEFAULT_BOOST)
    if not raw:
        return out
    try:
        data = json.loads(raw)
        for k, v in data.items():
            if k in out:
                out[k] = float(v)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return out


def compute_boosted_limits(
    current: dict[str, Any],
    *,
    amount_usd: float,
    boost: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Pure helper: current limits + payment amount → new limits."""
    cfg = boost or load_boost_config()
    amount = max(0.0, float(amount_usd or 0))
    usd_add = max(
        float(cfg.get("usd_month_add_min") or 0),
        amount * float(cfg.get("usd_month_add_factor") or 0),
    )
    return {
        "max_tasks_per_day": int(current.get("max_tasks_per_day") or 0)
        + int(cfg.get("tasks_per_day_add") or 0),
        "max_agent_runs_per_day": int(current.get("max_agent_runs_per_day") or 0)
        + int(cfg.get("runs_per_day_add") or 0),
        "max_concurrent_tasks": int(current.get("max_concurrent_tasks") or 0)
        + int(cfg.get("concurrent_add") or 0),
        "max_estimated_usd_per_month": round(
            float(current.get("max_estimated_usd_per_month") or 0) + usd_add, 4
        ),
    }


def next_plan_tier(current_tier: str | None, grant_count: int) -> str:
    tier = (current_tier or "free").lower()
    if grant_count >= 3 or tier == "pro":
        return "pro"
    if grant_count >= 1 or tier in {"starter", "pro"}:
        return "starter" if tier == "free" else tier
    return "free"


class QuotaService:
    def __init__(
        self,
        database_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
        billing: BillingService | None = None,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.tenant_id = tenant_id
        self.billing = billing or BillingService(database_url=self.database_url, tenant_id=tenant_id)

    def get(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        tid = tenant_id or self.tenant_id
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT tenant_id::text,
                       max_tasks_per_day,
                       max_agent_runs_per_day,
                       max_concurrent_tasks,
                       max_estimated_usd_per_month::float AS max_estimated_usd_per_month,
                       enabled,
                       COALESCE(plan_tier, 'free') AS plan_tier,
                       last_paid_at,
                       updated_at
                FROM tenant_quotas
                WHERE tenant_id = %s::uuid
                """,
                (tid,),
            ).fetchone()
        if not row:
            return {"tenant_id": tid, **_DEFAULTS, "last_paid_at": None, "updated_at": None, "exists": False}
        out = dict(row)
        out["exists"] = True
        for key in ("updated_at", "last_paid_at"):
            if out.get(key) is not None:
                out[key] = out[key].isoformat()
        return out
    def upsert(
        self,
        *,
        tenant_id: str | None = None,
        max_tasks_per_day: int | None = None,
        max_agent_runs_per_day: int | None = None,
        max_concurrent_tasks: int | None = None,
        max_estimated_usd_per_month: float | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        tid = tenant_id or self.tenant_id
        current = self.get(tenant_id=tid)
        values = {
            "max_tasks_per_day": int(
                max_tasks_per_day
                if max_tasks_per_day is not None
                else current.get("max_tasks_per_day") or _DEFAULTS["max_tasks_per_day"]
            ),
            "max_agent_runs_per_day": int(
                max_agent_runs_per_day
                if max_agent_runs_per_day is not None
                else current.get("max_agent_runs_per_day") or _DEFAULTS["max_agent_runs_per_day"]
            ),
            "max_concurrent_tasks": int(
                max_concurrent_tasks
                if max_concurrent_tasks is not None
                else current.get("max_concurrent_tasks") or _DEFAULTS["max_concurrent_tasks"]
            ),
            "max_estimated_usd_per_month": float(
                max_estimated_usd_per_month
                if max_estimated_usd_per_month is not None
                else current.get("max_estimated_usd_per_month")
                or _DEFAULTS["max_estimated_usd_per_month"]
            ),
            "enabled": bool(enabled if enabled is not None else current.get("enabled", True)),
        }
        # Clamp to sane ranges
        values["max_tasks_per_day"] = max(0, min(values["max_tasks_per_day"], 1_000_000))
        values["max_agent_runs_per_day"] = max(0, min(values["max_agent_runs_per_day"], 10_000_000))
        values["max_concurrent_tasks"] = max(0, min(values["max_concurrent_tasks"], 100_000))
        values["max_estimated_usd_per_month"] = max(
            0.0, min(values["max_estimated_usd_per_month"], 1_000_000.0)
        )

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            conn.execute(
                """
                INSERT INTO tenant_quotas (
                  tenant_id, max_tasks_per_day, max_agent_runs_per_day,
                  max_concurrent_tasks, max_estimated_usd_per_month, enabled, updated_at
                ) VALUES (
                  %s::uuid, %s, %s, %s, %s, %s, now()
                )
                ON CONFLICT (tenant_id) DO UPDATE SET
                  max_tasks_per_day = EXCLUDED.max_tasks_per_day,
                  max_agent_runs_per_day = EXCLUDED.max_agent_runs_per_day,
                  max_concurrent_tasks = EXCLUDED.max_concurrent_tasks,
                  max_estimated_usd_per_month = EXCLUDED.max_estimated_usd_per_month,
                  enabled = EXCLUDED.enabled,
                  updated_at = now()
                """,
                (
                    tid,
                    values["max_tasks_per_day"],
                    values["max_agent_runs_per_day"],
                    values["max_concurrent_tasks"],
                    values["max_estimated_usd_per_month"],
                    values["enabled"],
                ),
            )
            conn.commit()
        return self.get(tenant_id=tid)

    def usage_snapshot(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        tid = tenant_id or self.tenant_id
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            day = conn.execute(
                """
                SELECT COUNT(*)::int AS tasks_today
                FROM tasks
                WHERE tenant_id = %s::uuid
                  AND created_at >= date_trunc('day', now())
                """,
                (tid,),
            ).fetchone()
            runs = conn.execute(
                """
                SELECT COUNT(*)::int AS runs_today
                FROM agent_runs
                WHERE tenant_id = %s::uuid
                  AND created_at >= date_trunc('day', now())
                """,
                (tid,),
            ).fetchone()
            concurrent_row = conn.execute(
                """
                SELECT COUNT(*)::int AS concurrent
                FROM tasks
                WHERE tenant_id = %s::uuid
                  AND status IN ('running', 'waiting_for_user', 'created')
                """,
                (tid,),
            ).fetchone()

        month = self.billing.usage(days=30, tenant_id=tid)
        return {
            "tenant_id": tid,
            "as_of": datetime.now(timezone.utc).isoformat(),
            "tasks_today": int((day or {}).get("tasks_today") or 0),
            "agent_runs_today": int((runs or {}).get("runs_today") or 0),
            "concurrent_tasks": int((concurrent_row or {}).get("concurrent") or 0),
            "estimated_usd_30d": float(month.get("estimated_total_usd") or 0),
        }

    def status(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        tid = tenant_id or self.tenant_id
        limits = self.get(tenant_id=tid)
        usage = self.usage_snapshot(tenant_id=tid)
        return {
            "tenant_id": tid,
            "enforcement": quotas_enabled(),
            "payment_boost": payment_boost_enabled(),
            "limits": limits,
            "usage": usage,
            "headroom": {
                "tasks_today": max(
                    0, int(limits["max_tasks_per_day"]) - usage["tasks_today"]
                ),
                "agent_runs_today": max(
                    0, int(limits["max_agent_runs_per_day"]) - usage["agent_runs_today"]
                ),
                "concurrent_tasks": max(
                    0, int(limits["max_concurrent_tasks"]) - usage["concurrent_tasks"]
                ),
                "estimated_usd_30d": max(
                    0.0,
                    float(limits["max_estimated_usd_per_month"]) - usage["estimated_usd_30d"],
                ),
            },
            "grants": self.list_grants(tenant_id=tid, limit=5),
        }

    def list_grants(self, *, tenant_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        tid = tenant_id or self.tenant_id
        limit = max(1, min(int(limit), 100))
        try:
            with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
                rows = conn.execute(
                    """
                    SELECT id::text, invoice_id::text, stripe_event_id,
                           amount_usd::float AS amount_usd,
                           before_limits, after_limits, created_at
                    FROM tenant_quota_grants
                    WHERE tenant_id = %s::uuid
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (tid, limit),
                ).fetchall()
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for r in rows:
            item = dict(r)
            if item.get("created_at") is not None:
                item["created_at"] = item["created_at"].isoformat()
            out.append(item)
        return out

    def grant_after_payment(
        self,
        *,
        tenant_id: str,
        invoice_id: str | None,
        amount_usd: float,
        stripe_event_id: str | None = None,
    ) -> dict[str, Any]:
        """Idempotent quota boost after a paid invoice (Phase 33)."""
        if not payment_boost_enabled():
            return {"skipped": True, "reason": "QUOTA_PAYMENT_BOOST off"}
        if not invoice_id:
            return {"skipped": True, "reason": "no invoice_id"}

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            existing = conn.execute(
                "SELECT id::text FROM tenant_quota_grants WHERE invoice_id = %s::uuid",
                (invoice_id,),
            ).fetchone()
            if existing:
                return {
                    "skipped": True,
                    "duplicate": True,
                    "grant_id": existing["id"],
                    "invoice_id": invoice_id,
                }

            before = self.get(tenant_id=tenant_id)
            after_limits = compute_boosted_limits(before, amount_usd=amount_usd)
            # clamp
            after_limits["max_tasks_per_day"] = max(
                0, min(after_limits["max_tasks_per_day"], 1_000_000)
            )
            after_limits["max_agent_runs_per_day"] = max(
                0, min(after_limits["max_agent_runs_per_day"], 10_000_000)
            )
            after_limits["max_concurrent_tasks"] = max(
                0, min(after_limits["max_concurrent_tasks"], 100_000)
            )
            after_limits["max_estimated_usd_per_month"] = max(
                0.0, min(after_limits["max_estimated_usd_per_month"], 1_000_000.0)
            )

            grant_count_row = conn.execute(
                "SELECT COUNT(*)::int AS n FROM tenant_quota_grants WHERE tenant_id = %s::uuid",
                (tenant_id,),
            ).fetchone()
            grant_count = int((grant_count_row or {}).get("n") or 0) + 1
            tier = next_plan_tier(before.get("plan_tier"), grant_count)

            before_payload = {
                "max_tasks_per_day": before.get("max_tasks_per_day"),
                "max_agent_runs_per_day": before.get("max_agent_runs_per_day"),
                "max_concurrent_tasks": before.get("max_concurrent_tasks"),
                "max_estimated_usd_per_month": before.get("max_estimated_usd_per_month"),
                "plan_tier": before.get("plan_tier"),
            }

            conn.execute(
                """
                INSERT INTO tenant_quotas (
                  tenant_id, max_tasks_per_day, max_agent_runs_per_day,
                  max_concurrent_tasks, max_estimated_usd_per_month, enabled,
                  plan_tier, last_paid_at, updated_at
                ) VALUES (
                  %s::uuid, %s, %s, %s, %s, COALESCE(
                    (SELECT enabled FROM tenant_quotas WHERE tenant_id = %s::uuid), true
                  ),
                  %s, now(), now()
                )
                ON CONFLICT (tenant_id) DO UPDATE SET
                  max_tasks_per_day = EXCLUDED.max_tasks_per_day,
                  max_agent_runs_per_day = EXCLUDED.max_agent_runs_per_day,
                  max_concurrent_tasks = EXCLUDED.max_concurrent_tasks,
                  max_estimated_usd_per_month = EXCLUDED.max_estimated_usd_per_month,
                  plan_tier = EXCLUDED.plan_tier,
                  last_paid_at = now(),
                  updated_at = now()
                """,
                (
                    tenant_id,
                    after_limits["max_tasks_per_day"],
                    after_limits["max_agent_runs_per_day"],
                    after_limits["max_concurrent_tasks"],
                    after_limits["max_estimated_usd_per_month"],
                    tenant_id,
                    tier,
                ),
            )
            row = conn.execute(
                """
                INSERT INTO tenant_quota_grants (
                  tenant_id, invoice_id, stripe_event_id, amount_usd,
                  before_limits, after_limits
                ) VALUES (
                  %s::uuid, %s::uuid, %s, %s, %s::jsonb, %s::jsonb
                )
                RETURNING id::text, created_at
                """,
                (
                    tenant_id,
                    invoice_id,
                    stripe_event_id,
                    float(amount_usd or 0),
                    json.dumps(before_payload),
                    json.dumps({**after_limits, "plan_tier": tier}),
                ),
            ).fetchone()
            conn.commit()

        return {
            "skipped": False,
            "grant_id": row["id"],
            "invoice_id": invoice_id,
            "tenant_id": tenant_id,
            "amount_usd": float(amount_usd or 0),
            "plan_tier": tier,
            "before": before_payload,
            "after": {**after_limits, "plan_tier": tier},
            "created_at": row["created_at"].isoformat(),
        }

    def assert_can_create_task(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        if not quotas_enabled():
            return {"skipped": True, "reason": "TENANT_QUOTAS off"}
        snap = self.status(tenant_id=tenant_id)
        limits = snap["limits"]
        usage = snap["usage"]
        if not limits.get("enabled", True):
            return snap

        if usage["concurrent_tasks"] >= int(limits["max_concurrent_tasks"]):
            raise QuotaExceeded(
                "quota_concurrent",
                f"concurrent tasks {usage['concurrent_tasks']} >= limit {limits['max_concurrent_tasks']}",
                snapshot=snap,
            )
        if usage["tasks_today"] >= int(limits["max_tasks_per_day"]):
            raise QuotaExceeded(
                "quota_tasks_per_day",
                f"tasks today {usage['tasks_today']} >= limit {limits['max_tasks_per_day']}",
                snapshot=snap,
            )
        if usage["agent_runs_today"] >= int(limits["max_agent_runs_per_day"]):
            raise QuotaExceeded(
                "quota_runs_per_day",
                f"agent runs today {usage['agent_runs_today']} >= limit {limits['max_agent_runs_per_day']}",
                snapshot=snap,
            )
        if usage["estimated_usd_30d"] >= float(limits["max_estimated_usd_per_month"]):
            raise QuotaExceeded(
                "quota_usd_month",
                f"estimated USD 30d {usage['estimated_usd_30d']} >= limit {limits['max_estimated_usd_per_month']}",
                snapshot=snap,
            )
        return snap
