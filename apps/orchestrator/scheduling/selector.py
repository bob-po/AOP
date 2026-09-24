"""Phase 5.11 — Intelligent Scheduler (selection only; Router stays discovery/filter)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from scheduling.capability import Requirement, filter_by_capability
from scheduling.priority import effective_priority
from scheduling.reliability import ReliabilityService


@dataclass
class ScheduleDecision:
    selected: Optional[dict[str, Any]] = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    excluded: list[dict[str, Any]] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    reason: str = ""
    estimated_cost: float = 0.0
    estimated_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class IntelligentScheduler:
    """
    score =
      capability_score
    + availability_score
    + reliability_score
    + latency_score
    + resource_score
    - cost_penalty
    - queue_penalty
    """

    def __init__(self, reliability: ReliabilityService | None = None):
        self.reliability = reliability or ReliabilityService()

    def select(
        self,
        candidates: list[dict[str, Any]],
        *,
        requirement: Requirement | dict[str, Any] | None = None,
        exclude_agent_ids: set[str] | list[str] | None = None,
        max_cost: float | None = None,
        max_latency_ms: float | None = None,
        task_priority: str = "NORMAL",
        tenant_weight: float = 1.0,
        estimated_cost_by_agent: dict[str, float] | None = None,
    ) -> ScheduleDecision:
        req = (
            requirement
            if isinstance(requirement, Requirement)
            else Requirement.from_dict(requirement or {})
        )
        excluded: list[dict[str, Any]] = []
        pool = list(candidates)

        excludes = {str(x) for x in (exclude_agent_ids or []) if x}
        if excludes:
            kept = []
            for c in pool:
                aid = str(c.get("agent_id") or "")
                if aid in excludes:
                    excluded.append({"agent_id": aid, "reason": "excluded"})
                else:
                    kept.append(c)
            pool = kept

        if req.skill or req.require_gpu or req.modalities or req.models:
            pool, cap_ex = filter_by_capability(pool, req)
            excluded.extend(cap_ex)

        scores: dict[str, float] = {}
        scored: list[tuple[float, dict[str, Any]]] = []
        cost_map = estimated_cost_by_agent or {}

        for c in pool:
            aid = str(c.get("agent_id") or "")
            cap_s = float(c.get("capability_score") or 0.7)
            # availability from status / lifecycle
            status = (c.get("status") or "").lower()
            avail = 1.0 if status in {"online", "running"} else 0.0
            if c.get("lifecycle_state") in {"DRAINING", "OFFLINE"}:
                avail = 0.0
            rel_s = self.reliability.score(aid)
            # latency: prefer lower (normalize vs 5s)
            lat = float(c.get("latency_ms") or c.get("avg_latency_ms") or 500.0)
            if max_latency_ms and lat > max_latency_ms:
                excluded.append({"agent_id": aid, "reason": "latency_exceeded"})
                continue
            lat_s = max(0.0, 1.0 - (lat / 5000.0))
            # resource: inverse of load / queue
            load = float(c.get("load") or 0.0)
            qdepth = float(c.get("queue_depth") or 0.0)
            resource_s = max(0.0, 1.0 - load) * max(0.0, 1.0 - min(qdepth, 20) / 20.0)
            cost = float(cost_map.get(aid) or c.get("estimated_cost") or 0.0)
            if max_cost is not None and cost > max_cost:
                excluded.append({"agent_id": aid, "reason": "cost_exceeded"})
                continue
            cost_penalty = min(1.0, cost / max(max_cost or 1.0, 0.01))
            queue_penalty = min(1.0, qdepth / 20.0)

            score = (
                0.25 * cap_s
                + 0.15 * avail
                + 0.20 * rel_s
                + 0.15 * lat_s
                + 0.15 * resource_s
                - 0.05 * cost_penalty
                - 0.05 * queue_penalty
            )
            # Fair priority nudge (does not publish rankings)
            score += 0.01 * (
                effective_priority(priority=task_priority, tenant_weight=tenant_weight) / 1000.0
            )
            scores[aid] = round(score, 6)
            scored.append((score, {**c, "schedule_score": round(score, 6)}))

        scored.sort(key=lambda x: -x[0])
        ranked = [c for _, c in scored]
        selected = ranked[0] if ranked else None
        est_lat = float((selected or {}).get("latency_ms") or 0.0)
        est_cost = float(
            cost_map.get(str((selected or {}).get("agent_id") or ""), 0.0)
            if selected
            else 0.0
        )
        return ScheduleDecision(
            selected=selected,
            candidates=ranked,
            excluded=excluded,
            scores=scores,
            reason="selected" if selected else "no_candidates",
            estimated_cost=est_cost,
            estimated_latency_ms=est_lat,
        )


__all__ = ["IntelligentScheduler", "ScheduleDecision"]
