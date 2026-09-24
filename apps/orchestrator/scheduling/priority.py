"""Phase 5.6 — Priority + aging fairness."""

from __future__ import annotations

import time
from typing import Any

PRIORITY_WEIGHT = {
    "CRITICAL": 1000,
    "HIGH": 100,
    "NORMAL": 10,
    "LOW": 1,
}


def base_priority_score(priority: str | None) -> float:
    return float(PRIORITY_WEIGHT.get((priority or "NORMAL").upper(), 10))


def aging_boost(*, queued_at: float | None, now: float | None = None, factor: float = 0.1) -> float:
    """Waiting time factor — prevents permanent starvation of LOW."""
    if queued_at is None:
        return 0.0
    now = now if now is not None else time.time()
    waited = max(0.0, now - float(queued_at))
    # +1 effective priority unit per 10s * factor scaling
    return waited * factor


def effective_priority(
    *,
    priority: str | None = "NORMAL",
    queued_at: float | None = None,
    tenant_weight: float = 1.0,
    now: float | None = None,
) -> float:
    """effective = base_priority + waiting_time_factor, scaled by tenant_weight."""
    base = base_priority_score(priority)
    aged = aging_boost(queued_at=queued_at, now=now)
    return (base + aged) * max(0.01, float(tenant_weight))


def sort_by_fair_priority(items: list[dict[str, Any]], *, now: float | None = None) -> list[dict[str, Any]]:
    """Stable sort: higher effective_priority first."""
    now = now if now is not None else time.time()

    def key(it: dict[str, Any]) -> float:
        return -effective_priority(
            priority=it.get("priority") or it.get("task_priority"),
            queued_at=it.get("queued_at"),
            tenant_weight=float(it.get("tenant_weight") or 1.0),
            now=now,
        )

    return sorted(items, key=key)


__all__ = [
    "PRIORITY_WEIGHT",
    "base_priority_score",
    "aging_boost",
    "effective_priority",
    "sort_by_fair_priority",
]
