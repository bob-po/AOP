"""Phase 5.13 — Offline scheduler simulator (no side effects)."""

from __future__ import annotations

from typing import Any

from scheduling.capability import Requirement
from scheduling.selector import IntelligentScheduler
from scheduling.reliability import ReliabilityService, AgentReliability


def simulate(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Input: {agents, tasks, policies}
    Output: selected_agents, estimated_cost, estimated_latency, queue_depth, retries
    """
    agents = list(payload.get("agents") or [])
    tasks = list(payload.get("tasks") or [])
    policies = payload.get("policies") or {}
    max_cost = policies.get("max_cost")
    rel = ReliabilityService()
    # Seed reliability from agent hints
    fake_recs = []
    for a in agents:
        for _ in range(int(a.get("successes") or 0)):
            fake_recs.append(
                type("R", (), {"agent_id": a.get("agent_id"), "state": "SUCCEEDED", "duration_ms": a.get("latency_ms", 100), "attempt": 0})()
            )
        for _ in range(int(a.get("failures") or 0)):
            fake_recs.append(
                type("R", (), {"agent_id": a.get("agent_id"), "state": "FAILED", "duration_ms": a.get("latency_ms", 100), "attempt": 1})()
            )
    if fake_recs:
        rel.compute_from_records(fake_recs)

    sched = IntelligentScheduler(reliability=rel)
    selected_agents: dict[str, Any] = {}
    total_cost = 0.0
    total_lat = 0.0
    queue_depth: dict[str, int] = {str(a.get("agent_id")): int(a.get("queue_depth") or 0) for a in agents}
    retries = 0

    for t in tasks:
        tid = str(t.get("task_id") or t.get("id") or len(selected_agents))
        req = Requirement.from_dict(t.get("requirement") or {"skill": t.get("skill")})
        decision = sched.select(
            agents,
            requirement=req,
            exclude_agent_ids=t.get("exclude_agent_ids"),
            max_cost=max_cost,
            task_priority=t.get("priority") or "NORMAL",
            estimated_cost_by_agent={
                str(a.get("agent_id")): float(a.get("estimated_cost") or 0.1) for a in agents
            },
        )
        if decision.selected:
            aid = str(decision.selected.get("agent_id"))
            selected_agents[tid] = {
                "agent_id": aid,
                "score": decision.scores.get(aid),
            }
            total_cost += float(decision.selected.get("estimated_cost") or 0.1)
            total_lat += float(decision.selected.get("latency_ms") or 100)
            queue_depth[aid] = queue_depth.get(aid, 0) + 1
            # mutate local agent queue for subsequent tasks
            for a in agents:
                if str(a.get("agent_id")) == aid:
                    a["queue_depth"] = queue_depth[aid]
        else:
            retries += 1
            selected_agents[tid] = None

    return {
        "selected_agents": selected_agents,
        "estimated_cost": round(total_cost, 6),
        "estimated_latency": round(total_lat, 2),
        "queue_depth": queue_depth,
        "retries": retries,
    }


__all__ = ["simulate"]
