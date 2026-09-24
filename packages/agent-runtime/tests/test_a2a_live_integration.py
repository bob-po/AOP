"""A2A OS — live end-to-end acceptance tests over REAL transport.

These tests drive real, separately-running Agent processes through the actual
A2A HTTP transport and the real OS (gateway/orchestrator) discovery + runtime
graph. They implement the Phase-1 acceptance scenarios that require genuine
cross-process collaboration (no mocks, no in-process simulation):

    Test 1  basic A2A call            -> a real Agent executes and returns a task
    Test 2  autonomous multi-hop      -> Research -> Analysis -> RAG, self-directed
    Test 3  dynamic selection         -> Discovery returns candidates, Router picks
    Test 6  no central orchestrator   -> task submitted straight to an Agent

Test 4 (reverse call A->B->A) and Test 5 (governance limits) exercise the same
real governance/runtime code hermetically in ``test_collaboration.py`` and
``test_a2a_closed_loop.py`` (deterministic, no live stack required).

The whole module SKIPS when the OS is not reachable, so it never breaks a normal
offline ``pytest`` run. To execute it, bring up the stack with autonomous
delegation enabled (see scripts/a2a_autonomous_demo.py header) and run:

    pytest packages/agent-runtime/tests/test_a2a_live_integration.py -v
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

OS_URL = (os.getenv("A2A_OS_URL") or "http://127.0.0.1:8080").rstrip("/")
API_KEY = os.getenv("A2A_OS_API_KEY")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _os_available() -> bool:
    try:
        r = httpx.get(f"{OS_URL}/health", headers=_headers(), timeout=5)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(
    not _os_available(),
    reason=f"A2A OS not reachable at {OS_URL} (start the live stack to run)",
)


# ── helpers ──────────────────────────────────────────────────────────────

def _os_post(path: str, payload: dict) -> dict:
    r = httpx.post(f"{OS_URL}{path}", json=payload, headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def _os_get(path: str) -> dict:
    r = httpx.get(f"{OS_URL}{path}", headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def _agent_rpc(endpoint: str, method: str, params: dict) -> dict:
    r = httpx.post(
        endpoint.rstrip("/") + "/",
        json={"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def _send_text(endpoint: str, text: str, skill: str | None = None) -> dict:
    params = {
        "message": {
            "role": "user",
            "parts": [{"type": "text", "text": text}],
            "messageId": str(uuid.uuid4()),
        }
    }
    if skill:
        params["metadata"] = {"skillId": skill}
    return _agent_rpc(endpoint, "message/send", params)


def _name_map() -> dict[str, str]:
    data = _os_get("/v1/agents")
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


def _route_endpoint(skill: str) -> str:
    sel = _os_post("/v1/route", {"skill": skill, "required_skills": [skill]}).get("selected_agent")
    assert sel and sel.get("endpoint"), f"no online agent for skill={skill!r}"
    return sel["endpoint"]


# ── Test 1: basic A2A call (A -> B -> A over real transport) ──────────────

def test_test1_basic_a2a_call_returns_completed_task():
    """Submit straight to a leaf Agent (RAG) and get a completed task back."""
    endpoint = _route_endpoint("knowledge-search")
    resp = _send_text(endpoint, "What do we know about battery supply chains?", "knowledge-search")
    assert "error" not in resp, resp.get("error")
    result = resp["result"]
    assert result["id"]
    state = (result.get("status") or {}).get("state")
    assert state == "completed", state
    assert result.get("artifacts"), "expected at least one artifact back"


# ── Test 3: dynamic selection via Discovery + Router ─────────────────────

def test_test3_discovery_returns_candidates_and_router_selects():
    """Discovery yields candidates; Routing selects one of them (online)."""
    disc = _os_post("/v1/discover", {"required_skills": ["web-search"]})
    cands = disc.get("candidates") or []
    assert cands, "discovery returned no candidates for web-search"
    route = _os_post("/v1/route", {"skill": "web-search", "required_skills": ["web-search"]})
    sel = route.get("selected_agent")
    assert sel, "router selected no agent"
    cand_ids = {c.get("agent_id") or c.get("agent_key") for c in cands}
    assert (sel.get("agent_id") or sel.get("agent_key")) in cand_ids
    assert sel.get("status") == "online"


# ── Test 2 + Test 6: autonomous multi-hop with NO orchestrator ───────────

def test_test2_test6_autonomous_multihop_no_orchestrator():
    """Submit DIRECTLY to the Research Agent (bypassing the orchestrator) and
    verify it autonomously drives Research -> Analysis -> RAG, recorded in the
    real runtime execution graph."""
    names = _name_map()

    def nm(x):
        return names.get(str(x), str(x))

    entry = _route_endpoint("research")
    resp = _send_text(
        entry,
        "Research the electric-vehicle market and analyze the competitive "
        "landscape, grounding the analysis in the internal knowledge base.",
        "research",
    )
    assert "error" not in resp, resp.get("error")
    result = resp["result"]
    root = result["id"]

    # Test 6: the entry Agent autonomously delegated (no orchestrator involved).
    delegated = (result.get("metadata") or {}).get("autonomous_delegation")
    assert delegated, "entry Agent did not autonomously delegate (is A2A_OS_URL set on agents?)"

    # Test 2: the real runtime graph shows the multi-hop chain, correctly nested.
    graph = _os_get(f"/v1/runtime/graph/{root}")
    edges = graph["edges"]
    assert graph["max_depth"] >= 2, graph["max_depth"]

    search_edge = next(
        (e for e in edges if nm(e["caller_agent_id"]) == "search-agent"
         and e["skill"] == "business-analysis"),
        None,
    )
    rag_edge = next(
        (e for e in edges if nm(e["caller_agent_id"]) == "analysis-agent"
         and e["skill"] == "knowledge-search"),
        None,
    )
    assert search_edge, f"missing Research->Analysis edge in {[(nm(e['caller_agent_id']), e['skill']) for e in edges]}"
    assert rag_edge, "missing Analysis->RAG edge"
    # Lineage: Analysis->RAG must nest under Research->Analysis via parent_task_id.
    assert rag_edge["parent_task_id"] == search_edge["task_id"]
    # All edges share the same root_task_id and correlation_id.
    assert {e["root_task_id"] for e in edges} == {root}
    assert len({e["correlation_id"] for e in edges}) == 1
