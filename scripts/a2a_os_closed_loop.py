#!/usr/bin/env python3
"""A2A OS live acceptance demo — decentralized Agent-to-Agent collaboration.

Drives the *new* A2A OS infrastructure against running services and prints the
runtime execution graph. No central orchestrator decides the steps: the OS only
provides discovery / routing / graph, and Agents decide whom to call.

Prereqs (see docs/guides/getting-started.md):
  - Postgres + Redis up, migrations applied (018_a2a_runtime_graph)
  - Orchestrator on :8090  (uvicorn main:app --port 8090)
  - Gateway on :8080       (cd apps/gateway && go run ./cmd)
  - Agents registered      (python scripts/start_and_register_agents.py)

Usage:
  python scripts/a2a_os_closed_loop.py                 # via orchestrator :8090
  A2A_OS_URL=http://127.0.0.1:8080 python scripts/a2a_os_closed_loop.py   # via gateway

Env:
  A2A_OS_URL          OS base URL (default http://127.0.0.1:8090)
  A2A_OS_API_KEY      bearer key when going through an auth-required gateway
  DEMO_ROOT_SKILL     skill the demo "root" agent delegates on (default business-analysis)
"""

from __future__ import annotations

import os
import sys
import uuid

import httpx

OS_URL = (os.getenv("A2A_OS_URL") or "http://127.0.0.1:8090").rstrip("/")
API_KEY = os.getenv("A2A_OS_API_KEY")
ROOT_SKILL = os.getenv("DEMO_ROOT_SKILL", "business-analysis")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _post(path: str, payload: dict) -> dict:
    r = httpx.post(f"{OS_URL}{path}", json=payload, headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _get(path: str) -> dict:
    r = httpx.get(f"{OS_URL}{path}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> int:
    print(f"A2A OS live demo against {OS_URL}\n" + "=" * 60)

    # 0) health
    try:
        print("health:", _get("/health"))
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] OS not reachable at {OS_URL}: {exc}")
        print("       Start orchestrator (and gateway/agents) first — see header.")
        return 2

    # 1) DISCOVER — capability-aware peer discovery (open to any Agent)
    print("\n[1] POST /v1/discover  required_skills=[knowledge-search]")
    disc = _post("/v1/discover", {"required_skills": ["knowledge-search"]})
    print(f"    candidates={len(disc['candidates'])} selected={disc['selected']}")
    for c in disc["candidates"][:5]:
        print(f"      - {c['agent_key']:<16} {c['status']:<8} {c['endpoint']} score={c['score']}")

    # 2) ROUTE — pick the best Agent for a skill
    print(f"\n[2] POST /v1/route  skill={ROOT_SKILL}")
    route = _post("/v1/route", {"skill": ROOT_SKILL})
    sel = route.get("selected_agent")
    print(f"    selected_agent={sel['agent_key'] if sel else None} endpoint={sel['endpoint'] if sel else None}")

    # 3) RUNTIME GRAPH — record a small A->B->C chain and read it back.
    #    (Real Agents report these edges automatically via the collaboration
    #     runtime; here we simulate the reporting to demonstrate the query.)
    root = "demo-root-" + uuid.uuid4().hex[:8]
    print(f"\n[3] POST /v1/runtime/edges  (simulated A->B->C, root={root})")
    chain = [
        ("user", "research-agent", None, "t-a", 0),
        ("research-agent", "analysis-agent", "t-a", "t-b", 1),
        ("analysis-agent", "rag-agent", "t-b", "t-c", 2),
    ]
    for caller, target, parent, tid, depth in chain:
        _post(
            "/v1/runtime/edges",
            {
                "caller_agent_id": caller,
                "target_agent_id": target,
                "root_task_id": root,
                "parent_task_id": parent,
                "task_id": tid,
                "correlation_id": root,
                "skill": ROOT_SKILL,
                "depth": depth,
                "status": "completed",
            },
        )
    graph = _get(f"/v1/runtime/graph/{root}")
    print(f"    kind={graph['kind']} edges={graph['edge_count']} max_depth={graph['max_depth']}")
    print(f"    agents={graph['agents']}")

    def show(node, indent=1):
        print(f"{'  ' * indent}{node['caller_agent_id']} -> {node['target_agent_id']} "
              f"(task={node['task_id']} depth={node['depth']})")
        for ch in node.get("children", []):
            show(ch, indent + 1)

    print("    runtime execution graph:")
    for r in graph["tree"]:
        show(r)

    print("\n" + "=" * 60)
    print("OK — discovery, routing and runtime graph all responded.")
    print("NOTE: this is a runtime execution graph, NOT a predefined workflow DAG.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
