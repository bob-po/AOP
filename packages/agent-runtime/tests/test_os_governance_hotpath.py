"""Phase 2 — OS governance is consulted on the delegate hot path.

Hermetic tests: MockTransport stubs /v1/governance/check|release so we prove
``delegate()`` actually calls the OS (allow / deny / release), without needing
Postgres or Redis.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agent_runtime.collaboration import (
    A2ACollaborationRuntime,
    CallContext,
    GovernanceConfig,
    GovernanceError,
    CALL_LIMIT_EXCEEDED,
    CYCLE_DETECTED,
)


class FakeClient:
    def __init__(self, endpoint, timeout):
        self.endpoint = endpoint
        self.timeout = timeout
        self.calls: list[dict] = []

    def send_text(self, text, **kwargs):
        self.calls.append({"text": text, **kwargs})
        return {"id": f"task-{len(self.calls)}", "status": "completed"}


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


def _runtime(handler, *, agent_id="agent-a", governance=None):
    clients: list[FakeClient] = []

    def factory(endpoint, timeout):
        c = FakeClient(endpoint, timeout)
        clients.append(c)
        return c

    rt = A2ACollaborationRuntime(
        agent_id=agent_id,
        os_base_url="http://os:8080",
        governance=governance or GovernanceConfig(use_os_governance=True),
        http_transport=httpx.MockTransport(handler),
        a2a_client_factory=factory,
    )
    return rt, clients


def test_delegate_calls_os_governance_check_and_release():
    posts: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        posts.append((path, body))
        if path in {"/v1/route", "/v1/discover"}:
            return httpx.Response(200, json=SELECTION)
        if path == "/v1/governance/check":
            return httpx.Response(
                200,
                json={
                    "allowed": True,
                    "code": "",
                    "reason": "",
                    "context": {
                        "inflight": {
                            "agent": 1,
                            "tenant": 1,
                            "agent_key": "a2a:inflight:agent:agent-a",
                            "tenant_key": "a2a:inflight:tenant:t",
                        }
                    },
                },
            )
        if path == "/v1/governance/release":
            return httpx.Response(200, json={"released": True})
        if path == "/v1/runtime/edges":
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(404, json={"error": "nf"})

    rt, clients = _runtime(handler)
    ctx = CallContext.from_inbound(
        agent_id="agent-a",
        correlation_id="corr",
        task_id="tA",
        root_task_id="root-1",
        depth=0,
    )
    rt.delegate("need b", context=ctx, skill="skill-b")

    paths = [p for p, _ in posts]
    assert "/v1/governance/check" in paths
    assert "/v1/governance/release" in paths
    check_body = next(b for p, b in posts if p == "/v1/governance/check")
    assert check_body["root_task_id"] == "root-1"
    assert check_body["caller_agent_id"] == "agent-a"
    assert check_body["target_agent_id"] == "id-b"
    assert check_body["caller_task_id"] == "tA"
    # idempotency key travels on the wire for retry safety
    assert clients[0].calls[0]["idempotency_key"].startswith("a2a-del-")


def test_os_governance_deny_blocks_call():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in {"/v1/route", "/v1/discover"}:
            return httpx.Response(200, json=SELECTION)
        if path == "/v1/governance/check":
            return httpx.Response(
                200,
                json={
                    "allowed": False,
                    "code": CALL_LIMIT_EXCEEDED,
                    "reason": "root calls exceed max",
                    "context": {},
                },
            )
        return httpx.Response(404, json={"error": "nf"})

    rt, clients = _runtime(handler)
    ctx = CallContext.from_inbound(
        agent_id="agent-a",
        correlation_id="corr",
        task_id="tA",
        root_task_id="root-1",
        depth=0,
    )
    with pytest.raises(GovernanceError) as ei:
        rt.delegate("need b", context=ctx, skill="skill-b")
    assert ei.value.code == CALL_LIMIT_EXCEEDED
    assert clients == [] or len(clients[0].calls) == 0


def test_limited_revisit_local_allows_a_b_a_then_blocks_runaway():
    """A→B→A is legal; another visit past max_agent_visits is CYCLE_DETECTED."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/v1/route", "/v1/discover"}:
            return httpx.Response(200, json=SELECTION)
        if request.url.path == "/v1/runtime/edges":
            return httpx.Response(201, json={"ok": True})
        # No governance stub → OS unreachable → local-only enforcement
        return httpx.Response(404, json={"error": "nf"})

    gov = GovernanceConfig(max_agent_visits=2, use_os_governance=False)
    rt, _ = _runtime(handler, agent_id="agent-b", governance=gov)

    # id-b visited once → second visit OK
    ok_ctx = CallContext(
        correlation_id="c",
        caller_agent_id="agent-a",
        root_task_id="r",
        depth=1,
        visited_agents=("agent-a", "id-b"),
    )
    assert rt.delegate("rev", context=ok_ctx, skill="s").target_agent_id == "id-b"

    # id-b visited twice already → third blocked
    bad = CallContext(
        correlation_id="c",
        caller_agent_id="agent-a",
        root_task_id="r",
        depth=3,
        visited_agents=("agent-a", "id-b", "agent-a", "id-b"),
    )
    with pytest.raises(GovernanceError) as ei:
        rt.delegate("loop", context=bad, skill="s")
    assert ei.value.code == CYCLE_DETECTED


def test_delegation_idempotency_key_is_stable():
    k1 = A2ACollaborationRuntime.delegation_idempotency_key(
        correlation_id="c",
        parent_task_id="p",
        target_agent_id="b",
        skill="s",
        text="hello",
    )
    k2 = A2ACollaborationRuntime.delegation_idempotency_key(
        correlation_id="c",
        parent_task_id="p",
        target_agent_id="b",
        skill="s",
        text="hello",
    )
    k3 = A2ACollaborationRuntime.delegation_idempotency_key(
        correlation_id="c",
        parent_task_id="p",
        target_agent_id="b",
        skill="s",
        text="different",
    )
    assert k1 == k2
    assert k1 != k3
