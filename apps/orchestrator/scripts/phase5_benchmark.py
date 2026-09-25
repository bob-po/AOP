#!/usr/bin/env python3
"""Phase 5.14 — offline scheduling benchmark (no live stack required).

Writes:
  docs/phases/phase-05/benchmark.json
  docs/phases/phase-05/benchmark.md
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from scheduling import SchedulingService, simulate

ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = ROOT / "docs" / "phases" / "phase-05"
OUT_JSON = OUT_DIR / "benchmark.json"
OUT_MD = OUT_DIR / "benchmark.md"


def _agents(n: int = 10) -> list[dict]:
    skills = ["web-research", "research-summarize", "code-execution", "code-assist"]
    out = []
    for i in range(n):
        out.append(
            {
                "agent_id": f"agent-{i}",
                "skills": [skills[i % len(skills)], "research"] if i % 3 == 0 else [skills[i % len(skills)]],
                "status": "online" if i % 7 != 0 else "offline",
                "latency_ms": 50 + (i * 37) % 900,
                "load": (i % 10) / 10.0,
                "queue_depth": i % 4,
                "estimated_cost": 0.05 + (i % 5) * 0.02,
                "successes": 20 - (i % 5),
                "failures": i % 3,
            }
        )
    return out


def _tasks(n: int = 100) -> list[dict]:
    skills = ["web-research", "research-summarize", "code-execution", "code-assist", "web-search"]
    prios = ["CRITICAL", "HIGH", "NORMAL", "LOW"]
    return [
        {
            "task_id": f"t-{i}",
            "skill": skills[i % len(skills)],
            "priority": prios[i % len(prios)],
            "tenant_id": f"tenant-{i % 5}",
        }
        for i in range(n)
    ]


def main() -> int:
    agents = _agents(10)
    tasks = _tasks(100)
    t0 = time.perf_counter()
    sim = simulate({"agents": [dict(a) for a in agents], "tasks": tasks, "policies": {"max_cost": 1.0}})
    elapsed = time.perf_counter() - t0

    selected = [v for v in sim["selected_agents"].values() if v]
    dist: dict[str, int] = {}
    for v in selected:
        aid = v["agent_id"]
        dist[aid] = dist.get(aid, 0) + 1

    # Reselection stress: fail agent-1 and reselect
    svc = SchedulingService()
    reselect_ok = 0
    for i in range(20):
        plan = svc.recovery_plan(error_code="TIMEOUT", agent_id="agent-1")
        out = svc.select(
            agents,
            requirement={"skill": "web-research"},
            exclude_agent_ids=plan["exclude_agent_ids"],
            estimated_cost=0.1,
        )
        if out.get("selected") and out["selected"]["agent_id"] != "agent-1":
            reselect_ok += 1

    # Budget deny rate
    svc.budget.ensure_tenant_budget("tenant-0", daily=0.01, monthly=0.01)
    from scheduling import TenantContext

    denied = 0
    for _ in range(10):
        out = svc.select(
            agents,
            requirement={"skill": "analysis"},
            estimated_cost=1.0,
            ctx=TenantContext(tenant_id="tenant-0"),
        )
        if out.get("selected") is None:
            denied += 1

    report = {
        "tasks": 100,
        "agents": 10,
        "tenants": 5,
        "success_rate": len(selected) / 100.0,
        "selected_count": len(selected),
        "retries": sim["retries"],
        "estimated_cost": sim["estimated_cost"],
        "estimated_latency": sim["estimated_latency"],
        "average_latency": (sim["estimated_latency"] / max(len(selected), 1)),
        "agent_distribution": dist,
        "queue_depth": sim["queue_depth"],
        "reselection_success_rate": reselect_ok / 20.0,
        "budget_deny_rate": denied / 10.0,
        "duration_s": round(elapsed, 6),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Phase 5 Benchmark",
        "",
        f"- Tasks: {report['tasks']}",
        f"- Agents: {report['agents']}",
        f"- Tenants: {report['tenants']}",
        f"- Success rate: {report['success_rate']:.2%}",
        f"- Estimated cost: {report['estimated_cost']}",
        f"- Estimated latency (sum): {report['estimated_latency']}",
        f"- Avg latency: {report['average_latency']:.2f}",
        f"- Retries (unscheduled): {report['retries']}",
        f"- Reselection success: {report['reselection_success_rate']:.2%}",
        f"- Budget deny rate: {report['budget_deny_rate']:.2%}",
        f"- Duration: {report['duration_s']}s",
        "",
        "## Agent distribution",
        "",
    ]
    for aid, n in sorted(dist.items(), key=lambda x: -x[1]):
        lines.append(f"- `{aid}`: {n}")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"wrote {OUT_JSON} and {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
