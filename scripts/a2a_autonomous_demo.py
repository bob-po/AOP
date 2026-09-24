#!/usr/bin/env python3
"""A2A OS — REAL autonomous Agent-to-Agent collaboration demo.

Unlike ``a2a_os_closed_loop.py`` (which *simulates* graph edges to demonstrate
the query API), this script drives **real, separately-running Agent processes**
over **real HTTP A2A transport** and proves the decentralized closed loop:

    User ──(direct A2A, no orchestrator)──▶ Research(search) Agent
                                              │  autonomously discovers + delegates
                                              ▼
                                          Analysis Agent
                                              │  autonomously discovers + delegates
                                              ▼
                                           RAG Agent
                                              ▲ results bubble back up ▲

Nothing here pre-wires Research→Analysis→RAG. The entry Agent decides at runtime
to delegate; the OS only provides discovery / routing / runtime-graph. The call
edges are the ones the Agents themselves reported to ``/v1/runtime/edges`` and
are read back from Postgres via ``/v1/runtime/graph/{root_task_id}``.

Prereqs (see docs/guides/getting-started.md):
  - Postgres + Redis + MinIO up, migration 018_a2a_runtime_graph applied
  - Orchestrator :8090, Gateway :8080
  - Agents launched WITH autonomous delegation enabled, e.g.:
        export A2A_OS_URL=http://127.0.0.1:8080
        export A2A_AUTONOMOUS=true
        export SEARCH_AGENT_DELEGATE_SKILL=business-analysis
        export ANALYSIS_KNOWLEDGE_SKILL=knowledge-search
        python scripts/start_and_register_agents.py

Usage:
  python scripts/a2a_autonomous_demo.py
  A2A_OS_URL=http://127.0.0.1:8080 python scripts/a2a_autonomous_demo.py

Env:
  A2A_OS_URL       OS base URL used for discovery/graph (default http://127.0.0.1:8080)
  A2A_OS_API_KEY   bearer key when the gateway requires auth
  DEMO_ENTRY_SKILL skill used to find the entry Agent (default research)
  DEMO_INPUT       the user goal submitted to the entry Agent
"""

from __future__ import annotations

import os
import sys
import uuid

import httpx

OS_URL = (os.getenv("A2A_OS_URL") or "http://127.0.0.1:8080").rstrip("/")
API_KEY = os.getenv("A2A_OS_API_KEY")
ENTRY_SKILL = os.getenv("DEMO_ENTRY_SKILL", "research")
DEMO_INPUT = os.getenv(
    "DEMO_INPUT",
    "Research the electric-vehicle market and analyze the competitive landscape, "
    "grounding the analysis in the internal knowledge base.",
)

# Expected autonomous chain (logical agent keys), outermost caller first.
EXPECTED_CHAIN = ["search-agent", "analysis-agent"]


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _os_post(path: str, payload: dict) -> dict:
    r = httpx.post(f"{OS_URL}{path}", json=payload, headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def _os_get(path: str) -> dict:
    r = httpx.get(f"{OS_URL}{path}", headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def _agent_rpc(endpoint: str, method: str, params: dict) -> dict:
    """Call an Agent's JSON-RPC A2A endpoint directly over real HTTP."""
    r = httpx.post(
        endpoint.rstrip("/") + "/",
        json={"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def _agent_key_map() -> dict[str, str]:
    """registry agent_id (UUID) -> logical agent_key, for readable graph output."""
    try:
        data = _os_get("/v1/agents")
    except Exception:  # noqa: BLE001
        return {}
    agents = data.get("agents", data) if isinstance(data, dict) else data
    out: dict[str, str] = {}
    for a in agents or []:
        aid = a.get("agent_id") or a.get("id")
        key = a.get("agent_key") or a.get("name")
        if aid:
            out[str(aid)] = key or str(aid)
        if key:
            out[str(key)] = key
    return out


def main() -> int:
    print(f"A2A OS REAL autonomous demo — OS at {OS_URL}")
    print("=" * 68)

    # 0) OS health (gateway proxies /health to orchestrator; tolerate 404).
    try:
        print("health:", _os_get("/health"))
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] OS not reachable at {OS_URL}: {exc}")
        print("       Start orchestrator + gateway + agents first (see header).")
        return 2

    names = _agent_key_map()

    def nm(x: str | None) -> str:
        return names.get(str(x), str(x)) if x else "?"

    # 1) DISCOVER the entry Agent via the OS (capability-based, open to anyone).
    print(f"\n[1] POST /v1/route  skill={ENTRY_SKILL}  (OS picks the entry Agent)")
    route = _os_post("/v1/route", {"skill": ENTRY_SKILL, "required_skills": [ENTRY_SKILL]})
    entry = route.get("selected_agent")
    if not entry or not entry.get("endpoint"):
        print(f"[FAIL] no online agent for skill={ENTRY_SKILL!r}")
        return 3
    entry_endpoint = entry["endpoint"]
    print(f"    entry Agent = {entry.get('agent_key')} @ {entry_endpoint}")

    # 2) Submit DIRECTLY to the entry Agent over real A2A HTTP.
    #    NO orchestrator, NO predefined DAG — the Agent decides what to delegate.
    print("\n[2] message/send → entry Agent (direct A2A, bypassing orchestrator)")
    print(f"    input: {DEMO_INPUT[:72]}...")
    resp = _agent_rpc(
        entry_endpoint,
        "message/send",
        {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": DEMO_INPUT}],
                "messageId": str(uuid.uuid4()),
            },
            "metadata": {"skillId": ENTRY_SKILL},
        },
    )
    result = resp.get("result") or {}
    root_task_id = result.get("id")
    if resp.get("error") or not root_task_id:
        print(f"[FAIL] entry Agent returned error: {resp.get('error')}")
        return 4
    meta = result.get("metadata") or {}
    delegated = meta.get("autonomous_delegation")
    print(f"    entry task_id (== root_task_id): {root_task_id}")
    print(f"    autonomous_delegation present:  {bool(delegated)}")
    if delegated:
        print(f"    delegation result preview:      {str(delegated)[:100]}...")

    # 3) Read back the REAL runtime execution graph the Agents reported.
    print(f"\n[3] GET /v1/runtime/graph/{root_task_id}  (edges reported by the Agents)")
    graph = _os_get(f"/v1/runtime/graph/{root_task_id}")
    print(f"    kind={graph['kind']} edges={graph['edge_count']} max_depth={graph['max_depth']}")

    def show(node, indent=2):
        print(
            f"{'  ' * indent}{nm(node['caller_agent_id'])} → {nm(node['target_agent_id'])}"
            f"  [skill={node['skill']} depth={node['depth']} status={node['status']}]"
        )
        for ch in node.get("children", []):
            show(ch, indent + 1)

    print("    runtime execution graph (NOT a predefined workflow DAG):")
    for r in graph["tree"]:
        show(r)

    # 4) Assert the autonomous multi-hop chain really happened.
    print("\n[4] Verifying the decentralized closed loop ...")
    edges = graph["edges"]
    callers = {nm(e["caller_agent_id"]) for e in edges}
    ok = True

    if not delegated:
        print("    [FAIL] entry Agent did not autonomously delegate.")
        ok = False
    else:
        print("    [ok] entry Agent autonomously delegated to a peer.")

    # search → analysis edge
    if not any(
        nm(e["caller_agent_id"]) == "search-agent" and e["skill"] == "business-analysis"
        for e in edges
    ):
        print("    [FAIL] missing search-agent → (business-analysis) edge.")
        ok = False
    else:
        print("    [ok] Research(search) → Analysis delegation recorded.")

    # analysis → rag edge, nested under the search→analysis task
    analysis_edge = next(
        (e for e in edges if nm(e["caller_agent_id"]) == "search-agent"), None
    )
    rag_edge = next(
        (e for e in edges if nm(e["caller_agent_id"]) == "analysis-agent"
         and e["skill"] == "knowledge-search"),
        None,
    )
    if not rag_edge:
        print("    [FAIL] missing analysis-agent → (knowledge-search) edge.")
        ok = False
    else:
        print("    [ok] Analysis → RAG delegation recorded (Analysis decided autonomously).")
        if analysis_edge and rag_edge.get("parent_task_id") == analysis_edge.get("task_id"):
            print("    [ok] graph nests Analysis→RAG under Research→Analysis (parent_task_id linkage).")
        else:
            print("    [WARN] edges present but not nested via parent_task_id.")

    if graph["max_depth"] < 2:
        print(f"    [FAIL] expected multi-hop depth ≥ 2, got {graph['max_depth']}.")
        ok = False
    else:
        print(f"    [ok] multi-hop depth = {graph['max_depth']} (≥ 2 hops, no orchestrator).")

    print("\n" + "=" * 68)
    if ok:
        print("PASS — real autonomous Research → Analysis → RAG collaboration over A2A,")
        print("       driven by the Agents themselves, with NO central orchestrator and")
        print("       NO predefined workflow DAG. Graph is traceable and governed.")
        return 0
    print("FAIL — autonomous closed loop did not complete as expected.")
    print("       Ensure agents were launched with A2A_OS_URL + delegate-skill env (header).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
