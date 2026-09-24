"""Phase 5.3 — ExecutionCost model + in-memory/Postgres cost store."""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from scheduling.context import DEFAULT_TENANT_ID, get_tenant_context


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionCost:
    task_id: str
    root_task_id: Optional[str] = None
    correlation_id: Optional[str] = None
    execution_op: str = "execute"
    agent_id: Optional[str] = None
    tenant_id: str = DEFAULT_TENANT_ID
    model: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    gpu_seconds: float = 0.0
    cpu_seconds: float = 0.0
    wall_time_ms: int = 0
    network_bytes: int = 0
    storage_bytes: int = 0
    estimated_cost: float = 0.0
    currency: str = "USD"
    attempt: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)
    id: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Simple default pricing (USD) — Policy can override later
_DEFAULT_RATES = {
    "input_token": 0.000001,
    "output_token": 0.000002,
    "gpu_second": 0.0005,
    "cpu_second": 0.00001,
    "wall_ms": 0.0,
}


def estimate_cost(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    gpu_seconds: float = 0.0,
    cpu_seconds: float = 0.0,
    wall_time_ms: int = 0,
    rates: dict[str, float] | None = None,
) -> float:
    r = {**_DEFAULT_RATES, **(rates or {})}
    total = (
        input_tokens * r["input_token"]
        + output_tokens * r["output_token"]
        + gpu_seconds * r["gpu_second"]
        + cpu_seconds * r["cpu_second"]
        + wall_time_ms * r["wall_ms"]
    )
    return round(float(total), 8)


class CostStore:
    """In-memory cost store for hermetic tests."""

    def __init__(self):
        self._lock = threading.RLock()
        self._rows: list[ExecutionCost] = []

    def record(self, cost: ExecutionCost) -> ExecutionCost:
        with self._lock:
            # Replace same task/op/attempt
            self._rows = [
                c
                for c in self._rows
                if not (
                    c.task_id == cost.task_id
                    and c.execution_op == cost.execution_op
                    and c.attempt == cost.attempt
                )
            ]
            self._rows.append(cost)
            return cost

    def list_for_task(self, task_id: str) -> list[ExecutionCost]:
        with self._lock:
            return [c for c in self._rows if c.task_id == task_id]

    def list_for_root(self, root_task_id: str) -> list[ExecutionCost]:
        with self._lock:
            return [c for c in self._rows if c.root_task_id == root_task_id]

    def list_for_tenant(self, tenant_id: str) -> list[ExecutionCost]:
        with self._lock:
            return [c for c in self._rows if c.tenant_id == tenant_id]

    def aggregate(self, costs: list[ExecutionCost]) -> dict[str, Any]:
        return {
            "count": len(costs),
            "estimated_cost": round(sum(c.estimated_cost for c in costs), 8),
            "input_tokens": sum(c.input_tokens for c in costs),
            "output_tokens": sum(c.output_tokens for c in costs),
            "gpu_seconds": round(sum(c.gpu_seconds for c in costs), 6),
            "wall_time_ms": sum(c.wall_time_ms for c in costs),
            "currency": (costs[0].currency if costs else "USD"),
        }


class CostService:
    def __init__(self, store: CostStore | None = None):
        self.store = store or CostStore()

    def record_from_execution(
        self,
        rec: Any,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        gpu_seconds: float = 0.0,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExecutionCost:
        wall = int(getattr(rec, "duration_ms", 0) or 0)
        cpu_seconds = wall / 1000.0
        cost_val = estimate_cost(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            gpu_seconds=gpu_seconds,
            cpu_seconds=cpu_seconds,
            wall_time_ms=wall,
        )
        tctx = get_tenant_context()
        row = ExecutionCost(
            task_id=rec.task_id,
            root_task_id=rec.root_task_id,
            correlation_id=rec.correlation_id,
            execution_op=getattr(rec, "operation", "execute") or "execute",
            agent_id=getattr(rec, "agent_id", None),
            tenant_id=getattr(rec, "tenant_id", None) or tctx.tenant_id or DEFAULT_TENANT_ID,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            gpu_seconds=gpu_seconds,
            cpu_seconds=cpu_seconds,
            wall_time_ms=wall,
            estimated_cost=cost_val,
            attempt=int(getattr(rec, "attempt", 0) or 0),
            metadata=dict(metadata or {}),
        )
        saved = self.store.record(row)
        self._persist_postgres(saved)
        return saved

    def task_cost(self, task_id: str) -> dict[str, Any]:
        rows = self.store.list_for_task(task_id)
        # Also include root aggregation if this is a root
        root_rows = self.store.list_for_root(task_id)
        use = root_rows if root_rows else rows
        agg = self.store.aggregate(use)
        return {"task_id": task_id, **agg, "items": [c.to_dict() for c in use]}

    def task_breakdown(self, root_task_id: str) -> dict[str, Any]:
        rows = self.store.list_for_root(root_task_id)
        by_agent: dict[str, list[ExecutionCost]] = {}
        for c in rows:
            by_agent.setdefault(c.agent_id or "unknown", []).append(c)
        return {
            "root_task_id": root_task_id,
            "total": self.store.aggregate(rows),
            "by_agent": {
                aid: self.store.aggregate(cs) for aid, cs in by_agent.items()
            },
            "items": [c.to_dict() for c in rows],
        }

    def tenant_cost(self, tenant_id: str) -> dict[str, Any]:
        rows = self.store.list_for_tenant(tenant_id)
        return {"tenant_id": tenant_id, **self.store.aggregate(rows), "count": len(rows)}

    def _persist_postgres(self, cost: ExecutionCost) -> None:
        if os.getenv("EXECUTION_STORE", "memory").lower() == "memory":
            return
        if os.getenv("PYTEST_CURRENT_TEST"):
            return
        try:
            from db import connect
            from psycopg.types.json import Jsonb

            url = os.getenv("DATABASE_URL", "postgresql://aop:aop@127.0.0.1:5432/aop")
            with connect(url) as conn:
                with conn.transaction():
                    conn.execute(
                        """
                        INSERT INTO a2a_cost_records (
                          task_id, root_task_id, correlation_id, execution_op, agent_id,
                          tenant_id, model, input_tokens, output_tokens, gpu_seconds,
                          cpu_seconds, wall_time_ms, network_bytes, storage_bytes,
                          estimated_cost, currency, attempt, metadata
                        ) VALUES (
                          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                        )
                        ON CONFLICT (task_id, execution_op, attempt) DO UPDATE
                          SET estimated_cost = EXCLUDED.estimated_cost,
                              wall_time_ms = EXCLUDED.wall_time_ms,
                              input_tokens = EXCLUDED.input_tokens,
                              output_tokens = EXCLUDED.output_tokens
                        """,
                        (
                            cost.task_id,
                            cost.root_task_id,
                            cost.correlation_id,
                            cost.execution_op,
                            cost.agent_id,
                            cost.tenant_id,
                            cost.model,
                            cost.input_tokens,
                            cost.output_tokens,
                            cost.gpu_seconds,
                            cost.cpu_seconds,
                            cost.wall_time_ms,
                            cost.network_bytes,
                            cost.storage_bytes,
                            cost.estimated_cost,
                            cost.currency,
                            cost.attempt,
                            Jsonb(cost.metadata),
                        ),
                    )
        except Exception:  # noqa: BLE001
            pass


__all__ = ["ExecutionCost", "CostStore", "CostService", "estimate_cost"]
