"""Tests for the A2A OS agent-side collaboration runtime."""

from __future__ import annotations

import json

import httpx
import pytest

from agent_runtime.collaboration import (
    A2ACollaborationRuntime,
    CallContext,
    GovernanceConfig,
    GovernanceError,
    RECURSION_LIMIT_EXCEEDED,
    CYCLE_DETECTED,
    CALL_LIMIT_EXCEEDED,
    NO_AGENT_AVAILABLE,
)


class FakeClient:
    """Stand-in for a2a_sdk.A2AClient capturing send_text lineage args."""

    def __init__(self, endpoint, timeout):
        self.endpoint = endpoint
        self.timeout = timeout
        self.calls: list[dict] = []

    def send_text(self, text, **kwargs):
        self.calls.append({"text": text, **kwargs})
        return {"id": "task-xyz", "status": "completed", "endpoint": self.endpoint}


def _os_transport(route_response):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/route":
            return httpx.Response(200, json=route_response)
        if request.url.path == "/v1/discover":
            return httpx.Response(200, json=route_response)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def _runtime(route_response, *, governance=None, agent_id="agent-a"):
    clients: list[FakeClient] = []

    def factory(endpoint, timeout):
        c = FakeClient(endpoint, timeout)
        clients.append(c)
        return c

    rt = A2ACollaborationRuntime(
        agent_id=agent_id,
        os_base_url="http://os:8080",
        governance=governance or GovernanceConfig(),
        http_transport=_os_transport(route_response),
        a2a_client_factory=factory,
    )
    return rt, clients


SELECTION = {
    "selected_agent": {
        "agent_id": "id-b",
        "agent_key": "agent-b",
        "endpoint": "http://agent-b:8000/",
        "score": 0.9,
        "status": "online",
    },
    "candidates": [
        {"agent_id": "id-b", "agent_key": "agent-b", "endpoint": "http://agent-b:8000/", "score": 0.9}
    ],
}


def test_discover_posts_to_os():
    rt, _ = _runtime(SELECTION)
    out = rt.discover(required_skills=["rag"], capabilities={"streaming": True})
    assert out["selected_agent"]["agent_key"] == "agent-b"


def test_delegate_propagates_lineage():
    rt, clients = _runtime(SELECTION)
    ctx = CallContext(
        correlation_id="corr-1",
        caller_agent_id="agent-a",
        root_task_id="root-1",
        parent_task_id=None,
        depth=0,
        visited_agents=("agent-a",),
    )
    result = rt.delegate("need rag", context=ctx, skill="rag", self_task_id="task-a")
    assert result.target_agent_id == "id-b"
    assert result.depth == 1
    sent = clients[0].calls[0]
    assert sent["correlation_id"] == "corr-1"
    assert sent["root_task_id"] == "root-1"
    assert sent["parent_task_id"] == "task-a"
    assert sent["depth"] == 1
    assert sent["skill_id"] == "rag"


def test_delegate_uses_inbound_self_task_id_as_parent():
    """When an Agent delegates onward, the edge's parent_task_id must be the
    Agent's OWN inbound task id (ctx.self_task_id), so the OS runtime graph can
    nest caller-task -> callee-task across a real multi-hop chain."""
    edges: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/v1/route", "/v1/discover"}:
            return httpx.Response(200, json=SELECTION)
        if request.url.path == "/v1/runtime/edges":
            edges.append(json.loads(request.content))
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(404, json={"error": "not found"})

    clients: list[FakeClient] = []

    def factory(endpoint, timeout):
        c = FakeClient(endpoint, timeout)
        clients.append(c)
        return c

    rt = A2ACollaborationRuntime(
        agent_id="analysis-agent",
        os_base_url="http://os:8080",
        http_transport=httpx.MockTransport(handler),
        a2a_client_factory=factory,
    )
    # Inbound context as built by a2a_server.inbound_context: this Agent's own
    # task id is carried as self_task_id, its caller's task as parent_task_id.
    ctx = CallContext.from_inbound(
        agent_id="analysis-agent",
        correlation_id="corr-root",
        task_id="task-analysis",
        root_task_id="task-search",
        parent_task_id="task-search",
        depth=1,
    )
    assert ctx.self_task_id == "task-analysis"

    # No explicit self_task_id passed — must fall back to ctx.self_task_id.
    rt.delegate("need knowledge", context=ctx, skill="knowledge-search")

    sent = clients[0].calls[0]
    assert sent["parent_task_id"] == "task-analysis"
    assert sent["root_task_id"] == "task-search"
    assert sent["depth"] == 2
    assert len(edges) == 1
    assert edges[0]["parent_task_id"] == "task-analysis"
    assert edges[0]["root_task_id"] == "task-search"
    assert edges[0]["caller_agent_id"] == "analysis-agent"


def test_delegate_no_agent_available():
    rt, _ = _runtime({"selected_agent": None, "candidates": []})
    ctx = CallContext(correlation_id="c", caller_agent_id="a")
    with pytest.raises(GovernanceError) as ei:
        rt.delegate("x", context=ctx, skill="rag")
    assert ei.value.code == NO_AGENT_AVAILABLE


def test_governance_max_depth():
    gov = GovernanceConfig(max_delegation_depth=2)
    rt, _ = _runtime(SELECTION, governance=gov)
    ctx = CallContext(correlation_id="c", caller_agent_id="a", depth=2, visited_agents=("a",))
    with pytest.raises(GovernanceError) as ei:
        rt.delegate("x", context=ctx, skill="rag")
    assert ei.value.code == RECURSION_LIMIT_EXCEEDED


def test_governance_call_limit():
    gov = GovernanceConfig(max_calls_per_task=3)
    rt, _ = _runtime(SELECTION, governance=gov)
    ctx = CallContext(correlation_id="c", caller_agent_id="a", calls_made=3)
    with pytest.raises(GovernanceError) as ei:
        rt.delegate("x", context=ctx, skill="rag")
    assert ei.value.code == CALL_LIMIT_EXCEEDED


def test_governance_allows_reverse_call_but_blocks_runaway_cycle():
    """A -> B -> A is allowed; A -> B -> A -> B -> A is not (visit bound)."""
    gov = GovernanceConfig(max_delegation_depth=10, max_agent_visits=2)
    rt, _ = _runtime(SELECTION, governance=gov, agent_id="agent-b")
    # Chain already visited agent-b twice -> next visit to id-b would be the 3rd.
    ctx = CallContext(
        correlation_id="c",
        caller_agent_id="agent-a",
        depth=3,
        visited_agents=("agent-a", "id-b", "agent-a", "id-b"),
    )
    with pytest.raises(GovernanceError) as ei:
        rt.delegate("x", context=ctx, skill="rag")
    assert ei.value.code == CYCLE_DETECTED


def test_reverse_call_within_limit_succeeds():
    gov = GovernanceConfig(max_agent_visits=2)
    rt, _ = _runtime(SELECTION, governance=gov, agent_id="agent-b")
    # id-b visited once already; a second visit is within the bound.
    ctx = CallContext(
        correlation_id="c",
        caller_agent_id="agent-a",
        depth=1,
        visited_agents=("agent-a", "id-b"),
    )
    result = rt.delegate("x", context=ctx, skill="rag")
    assert result.target_agent_id == "id-b"


def test_call_context_child_increments():
    ctx = CallContext(correlation_id="c", caller_agent_id="a", root_task_id="r", depth=1, visited_agents=("a",))
    child = ctx.child("b", parent_task_id="t-a")
    assert child.depth == 2
    assert child.visited_agents == ("a", "b")
    assert child.parent_task_id == "t-a"
    assert child.root_task_id == "r"
    assert child.calls_made == ctx.calls_made + 1


def test_from_inbound_builds_chain():
    ctx = CallContext.from_inbound(
        agent_id="agent-b", correlation_id="c", task_id="t-b", root_task_id="r", depth=1
    )
    assert ctx.root_task_id == "r"
    assert ctx.visited_agents == ("agent-b",)
    assert ctx.caller_agent_id == "agent-b"
