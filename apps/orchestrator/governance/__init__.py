"""Phase 2.2 — OS-level governance, quota and budget.

This is the *trusted* authority for autonomous Agent-to-Agent collaboration.
Agents propose a delegation; the OS decides whether it is allowed based on
limits Agents cannot raise themselves:

* max delegation depth (reconstructed from the runtime graph, not caller-claimed)
* max visits of a single Agent along a branch (allows A->B->A, blocks runaway)
* max calls per root task
* cumulative + per-call budget (extensible units; never fabricated)
* agent / tenant in-flight concurrency
* task deadline / max lifetime

Counters are DB-atomic (row-locked upsert) and Redis-atomic (in-flight), so they
stay correct across the multiple processes of a real Agent network — no
in-process counter is the source of truth. Every rejection is recorded with a
stable code and full lineage (queryable from Task/Audit), never silently dropped.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from db import connect
from runtime_graph import RuntimeGraphService

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Stable governance error codes (shared with the agent-side runtime).
RECURSION_LIMIT_EXCEEDED = "RECURSION_LIMIT_EXCEEDED"
CYCLE_DETECTED = "CYCLE_DETECTED"
CALL_LIMIT_EXCEEDED = "CALL_LIMIT_EXCEEDED"
BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
CONCURRENCY_LIMIT_EXCEEDED = "CONCURRENCY_LIMIT_EXCEEDED"
DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
NO_AGENT_AVAILABLE = "NO_AGENT_AVAILABLE"
POLICY_DISABLED = "POLICY_DISABLED"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BudgetMeter:
    """Extensible cost meter for A2A calls.

    There is no unified token/money metering across providers yet, so the
    default model charges a flat ``units_per_call``. Callers MAY supply a
    measured/estimated token cost; anything not actually measured is flagged
    ``estimated=True``. We never fabricate per-provider costs.
    """

    def __init__(self, units_per_call: float = 1.0):
        self.units_per_call = units_per_call

    def measure(self, requested_units: Optional[float], estimated: bool) -> tuple[float, bool]:
        if requested_units is None:
            return self.units_per_call, True  # flat default is an estimate
        return float(requested_units), bool(estimated)


@dataclass
class GovernanceDecision:
    allowed: bool
    code: str = ""
    reason: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "code": self.code,
            "reason": self.reason,
            "context": self.context,
        }


@dataclass
class Policy:
    max_delegation_depth: int = 5
    max_calls_per_root: int = 50
    max_agent_visits: int = 3
    max_agent_concurrency: int = 8
    max_tenant_concurrency: int = 64
    max_task_lifetime_s: int = 900
    max_budget_units_root: float = 1000.0
    max_budget_units_call: float = 100.0
    enabled: bool = True
    policy_id: Optional[str] = None
    name: str = "global-default"


_POLICY_FIELDS = (
    "max_delegation_depth", "max_calls_per_root", "max_agent_visits",
    "max_agent_concurrency", "max_tenant_concurrency", "max_task_lifetime_s",
    "max_budget_units_root", "max_budget_units_call", "enabled",
)


class GovernanceService:
    def __init__(
        self,
        database_url: str | None = None,
        redis_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
        runtime_graph: Optional[RuntimeGraphService] = None,
        budget_meter: Optional[BudgetMeter] = None,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL", "postgresql://aop:aop@127.0.0.1:5432/aop"
        )
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.tenant_id = tenant_id
        self.graph = runtime_graph or RuntimeGraphService(self.database_url)
        self.budget = budget_meter or BudgetMeter()
        self._redis = None

    # ── policy resolution (agent > tenant > global) ──────────────────────

    def load_policy(self, tenant_id: Optional[str], agent_id: Optional[str]) -> Policy:
        rows: list[dict[str, Any]] = []
        sql = """
            SELECT id::text, name, tenant_id::text, agent_id,
                   max_delegation_depth, max_calls_per_root, max_agent_visits,
                   max_agent_concurrency, max_tenant_concurrency, max_task_lifetime_s,
                   max_budget_units_root, max_budget_units_call, enabled
            FROM a2a_governance_policies
            WHERE enabled = true
              AND (agent_id = %s OR agent_id IS NULL)
              AND (tenant_id = %s OR tenant_id IS NULL)
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (agent_id, tenant_id or self.tenant_id)).fetchall()

        def specificity(r: dict[str, Any]) -> int:
            return (2 if r.get("agent_id") else 0) + (1 if r.get("tenant_id") else 0)

        policy = Policy()
        if rows:
            rows.sort(key=specificity)  # least specific first; most specific overrides
            for r in rows:
                for f in _POLICY_FIELDS:
                    if r.get(f) is not None:
                        setattr(policy, f, r[f])
            top = rows[-1]
            policy.policy_id = top.get("id")
            policy.name = top.get("name") or policy.name
        return policy

    # ── redis (in-flight concurrency, atomic) ────────────────────────────

    def _r(self):
        if self._redis is None:
            try:
                import redis  # local import: optional dependency

                self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:  # noqa: BLE001 - redis optional; concurrency check degrades
                self._redis = False
        return self._redis or None

    def _incr_inflight(self, key: str, ttl: int) -> Optional[int]:
        r = self._r()
        if r is None:
            return None
        try:
            val = r.incr(key)
            if val == 1:
                r.expire(key, ttl)
            return int(val)
        except Exception:  # noqa: BLE001
            return None

    def _decr_inflight(self, key: str) -> None:
        r = self._r()
        if r is None:
            return
        try:
            if r.decr(key) <= 0:
                r.delete(key)
        except Exception:  # noqa: BLE001
            pass

    # ── authoritative check + atomic reservation ─────────────────────────

    def check_and_reserve(
        self,
        *,
        root_task_id: str,
        caller_agent_id: str,
        target_agent_id: str,
        caller_task_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        requested_units: Optional[float] = None,
        units_estimated: bool = True,
        deadline: Optional[str] = None,
        claimed_depth: Optional[int] = None,
    ) -> GovernanceDecision:
        """Decide whether a proposed delegation is allowed, and if so atomically
        reserve its call + budget. Depth/visits are reconstructed from the OS's
        own runtime graph (anti-tamper); budget/calls are row-locked in the DB.
        """
        tenant = tenant_id or self.tenant_id
        policy = self.load_policy(tenant, caller_agent_id)
        if not policy.enabled:
            return self._deny(POLICY_DISABLED, "governance policy disabled",
                              root_task_id, correlation_id, caller_agent_id,
                              target_agent_id, tenant, 0, requested_units)

        # Authoritative branch lineage from recorded edges (not caller-claimed).
        branch = self.graph.branch_lineage(root_task_id, caller_task_id) if caller_task_id else {
            "agent_chain": [], "depth": 0, "agent_visits": {},
        }
        real_depth = int(branch.get("depth") or 0)
        # Fall back to claimed depth only if it is DEEPER (never shallower) than
        # the reconstructed depth, so a caller cannot under-report to bypass.
        new_depth = real_depth + 1
        if claimed_depth is not None:
            new_depth = max(new_depth, int(claimed_depth) + 1)

        visits = dict(branch.get("agent_visits") or {})
        target_visits = visits.get(target_agent_id, 0) + 1

        # depth / cycle limits
        if new_depth > policy.max_delegation_depth:
            return self._deny(RECURSION_LIMIT_EXCEEDED,
                              f"depth {new_depth} exceeds max {policy.max_delegation_depth}",
                              root_task_id, correlation_id, caller_agent_id,
                              target_agent_id, tenant, new_depth, requested_units)
        if target_visits > policy.max_agent_visits:
            return self._deny(CYCLE_DETECTED,
                              f"agent {target_agent_id!r} would be visited {target_visits} "
                              f"times (max {policy.max_agent_visits}); chain={branch.get('agent_chain')}",
                              root_task_id, correlation_id, caller_agent_id,
                              target_agent_id, tenant, new_depth, requested_units)

        units, estimated = self.budget.measure(requested_units, units_estimated)
        if units > policy.max_budget_units_call:
            return self._deny(BUDGET_EXCEEDED,
                              f"per-call units {units} exceed max {policy.max_budget_units_call}",
                              root_task_id, correlation_id, caller_agent_id,
                              target_agent_id, tenant, new_depth, units)

        # deadline (absolute) / max lifetime
        if deadline:
            try:
                dl = datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
                if dl.tzinfo is None:
                    dl = dl.replace(tzinfo=timezone.utc)
                if _utc_now() > dl:
                    return self._deny(DEADLINE_EXCEEDED, f"deadline {deadline} passed",
                                      root_task_id, correlation_id, caller_agent_id,
                                      target_agent_id, tenant, new_depth, units)
            except ValueError:
                pass

        # concurrency (Redis-atomic in-flight); reserve agent then tenant.
        agent_key = f"a2a:inflight:agent:{caller_agent_id}"
        tenant_key = f"a2a:inflight:tenant:{tenant}"
        ttl = max(30, policy.max_task_lifetime_s)
        agent_inflight = self._incr_inflight(agent_key, ttl)
        if agent_inflight is not None and agent_inflight > policy.max_agent_concurrency:
            self._decr_inflight(agent_key)
            return self._deny(CONCURRENCY_LIMIT_EXCEEDED,
                              f"agent {caller_agent_id!r} in-flight {agent_inflight} "
                              f"> max {policy.max_agent_concurrency}",
                              root_task_id, correlation_id, caller_agent_id,
                              target_agent_id, tenant, new_depth, units)
        tenant_inflight = self._incr_inflight(tenant_key, ttl)
        if tenant_inflight is not None and tenant_inflight > policy.max_tenant_concurrency:
            self._decr_inflight(tenant_key)
            if agent_inflight is not None:
                self._decr_inflight(agent_key)
            return self._deny(CONCURRENCY_LIMIT_EXCEEDED,
                              f"tenant in-flight {tenant_inflight} > max {policy.max_tenant_concurrency}",
                              root_task_id, correlation_id, caller_agent_id,
                              target_agent_id, tenant, new_depth, units)

        # calls-per-root + cumulative budget: atomic, row-locked in one txn.
        try:
            with connect(self.database_url) as conn:
                with conn.transaction():
                    row = conn.execute(
                        """
                        INSERT INTO a2a_budget_usage
                          (root_task_id, correlation_id, tenant_id, calls, units_used,
                           units_are_estimated, first_seen_at, updated_at)
                        VALUES (%s, %s, %s, 0, 0, %s, now(), now())
                        ON CONFLICT (root_task_id) DO UPDATE
                          SET updated_at = now()
                        RETURNING calls, units_used, first_seen_at
                        """,
                        (root_task_id, correlation_id, tenant, estimated),
                    ).fetchone()

                    calls = int(row["calls"]) + 1
                    new_units = float(row["units_used"]) + units
                    first_seen = row["first_seen_at"]

                    if calls > policy.max_calls_per_root:
                        conn.rollback()
                        self._release_inflight(agent_key, tenant_key, agent_inflight, tenant_inflight)
                        return self._deny(CALL_LIMIT_EXCEEDED,
                                          f"root calls {calls} exceed max {policy.max_calls_per_root}",
                                          root_task_id, correlation_id, caller_agent_id,
                                          target_agent_id, tenant, new_depth, units)
                    if new_units > policy.max_budget_units_root:
                        conn.rollback()
                        self._release_inflight(agent_key, tenant_key, agent_inflight, tenant_inflight)
                        return self._deny(BUDGET_EXCEEDED,
                                          f"root budget {new_units} would exceed max "
                                          f"{policy.max_budget_units_root}",
                                          root_task_id, correlation_id, caller_agent_id,
                                          target_agent_id, tenant, new_depth, units)
                    if first_seen is not None:
                        age = (_utc_now() - first_seen).total_seconds()
                        if age > policy.max_task_lifetime_s:
                            conn.rollback()
                            self._release_inflight(agent_key, tenant_key, agent_inflight, tenant_inflight)
                            return self._deny(DEADLINE_EXCEEDED,
                                              f"root task age {int(age)}s exceeds max lifetime "
                                              f"{policy.max_task_lifetime_s}s",
                                              root_task_id, correlation_id, caller_agent_id,
                                              target_agent_id, tenant, new_depth, units)

                    conn.execute(
                        """
                        UPDATE a2a_budget_usage
                           SET calls = %s, units_used = %s,
                               units_are_estimated = units_are_estimated OR %s,
                               updated_at = now()
                         WHERE root_task_id = %s
                        """,
                        (calls, new_units, estimated, root_task_id),
                    )
        except Exception as exc:  # noqa: BLE001
            self._release_inflight(agent_key, tenant_key, agent_inflight, tenant_inflight)
            return self._deny(QUOTA_EXCEEDED, f"governance store error: {exc}",
                              root_task_id, correlation_id, caller_agent_id,
                              target_agent_id, tenant, new_depth, units)

        return GovernanceDecision(
            allowed=True,
            code="",
            reason="",
            context={
                "root_task_id": root_task_id,
                "depth": new_depth,
                "calls": calls,
                "units_used": new_units,
                "units_are_estimated": estimated,
                "target_visits": target_visits,
                "agent_chain": branch.get("agent_chain"),
                "policy_id": policy.policy_id,
                "policy_name": policy.name,
                "inflight": {"agent": agent_inflight, "tenant": tenant_inflight,
                             "agent_key": agent_key, "tenant_key": tenant_key},
            },
        )

    def release(self, decision_ctx: dict[str, Any]) -> None:
        """Release in-flight concurrency reserved by a successful check."""
        inflight = (decision_ctx or {}).get("inflight") or {}
        if inflight.get("agent_key") and inflight.get("agent") is not None:
            self._decr_inflight(inflight["agent_key"])
        if inflight.get("tenant_key") and inflight.get("tenant") is not None:
            self._decr_inflight(inflight["tenant_key"])

    def _release_inflight(self, agent_key, tenant_key, agent_val, tenant_val) -> None:
        if agent_val is not None:
            self._decr_inflight(agent_key)
        if tenant_val is not None:
            self._decr_inflight(tenant_key)

    def _deny(self, code, reason, root_task_id, correlation_id, caller, target,
              tenant, depth, requested_units) -> GovernanceDecision:
        self.record_denial(
            root_task_id=root_task_id, correlation_id=correlation_id,
            caller_agent_id=caller, target_agent_id=target, tenant_id=tenant,
            code=code, reason=reason, depth=depth, requested_units=requested_units,
        )
        return GovernanceDecision(allowed=False, code=code, reason=reason,
                                  context={"root_task_id": root_task_id, "depth": depth})

    # ── audit ────────────────────────────────────────────────────────────

    def record_denial(self, *, root_task_id, correlation_id, caller_agent_id,
                      target_agent_id, tenant_id, code, reason, depth=0,
                      requested_units=None) -> None:
        try:
            with connect(self.database_url) as conn:
                conn.execute(
                    """
                    INSERT INTO a2a_governance_denials
                      (root_task_id, correlation_id, caller_agent_id, target_agent_id,
                       tenant_id, code, reason, depth, requested_units)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (root_task_id, correlation_id, caller_agent_id, target_agent_id,
                     tenant_id or self.tenant_id, code, reason, int(depth or 0),
                     requested_units),
                )
        except Exception:  # noqa: BLE001 - audit must never break the decision path
            pass

    def list_denials(self, *, root_task_id: Optional[str] = None,
                     code: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        clauses, params = [], []
        if root_task_id:
            clauses.append("root_task_id = %s")
            params.append(root_task_id)
        if code:
            clauses.append("code = %s")
            params.append(code)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(1, min(limit, 1000)))
        sql = f"""
            SELECT id, root_task_id, correlation_id, caller_agent_id, target_agent_id,
                   tenant_id::text, code, reason, depth, requested_units, created_at
            FROM a2a_governance_denials {where}
            ORDER BY id DESC LIMIT %s
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("created_at"), datetime):
                d["created_at"] = d["created_at"].isoformat()
            if d.get("requested_units") is not None:
                d["requested_units"] = float(d["requested_units"])
            out.append(d)
        return out


__all__ = [
    "GovernanceService", "GovernanceDecision", "Policy", "BudgetMeter",
    "RECURSION_LIMIT_EXCEEDED", "CYCLE_DETECTED", "CALL_LIMIT_EXCEEDED",
    "BUDGET_EXCEEDED", "QUOTA_EXCEEDED", "CONCURRENCY_LIMIT_EXCEEDED",
    "DEADLINE_EXCEEDED", "NO_AGENT_AVAILABLE", "POLICY_DISABLED",
]
