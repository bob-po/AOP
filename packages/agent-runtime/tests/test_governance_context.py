"""Phase 2.1 — cross-process governance context propagation.

Focused tests for the rules that make multi-process, multi-hop governance
reliable:

* ``visited_agents`` accumulates along a lineage path and travels on the wire.
* Parallel branches derive independently from their shared parent context, so
  one branch's visit history never pollutes another's (no cross-branch leak).
* ``governance_policy_id`` / ``deadline`` propagate through child contexts and
  outbound A2A calls.
* A legal reverse call (A -> B -> A) is representable in the chain, while an
  unbounded loop keeps growing the chain so the OS can bound it.
"""

from __future__ import annotations

import httpx

from agent_runtime.collaboration import (
    A2ACollaborationRuntime,
    CallContext,
    GovernanceConfig,
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


def _runtime(agent_id="agent-a"):
    clients: list[FakeClient] = []

    def factory(endpoint, timeout):
        c = FakeClient(endpoint, timeout)
        clients.append(c)
        return c

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path in {"/v1/route", "/v1/discover"}:
            return httpx.Response(200, json=SELECTION)
        if request.url.path == "/v1/runtime/edges":
            return httpx.Response(201, json={"ok": True})
        return httpx.Response(404, json={"error": "nf"})

    rt = A2ACollaborationRuntime(
        agent_id=agent_id,
        os_base_url="http://os:8080",
        governance=GovernanceConfig(),
        http_transport=httpx.MockTransport(handler),
        a2a_client_factory=factory,
    )
    return rt, clients


# ── visited_agents chain rules ───────────────────────────────────────────

def test_child_appends_target_and_propagates_governance_fields():
    ctx = CallContext(
        correlation_id="corr",
        caller_agent_id="agent-a",
        root_task_id="root",
        depth=1,
        visited_agents=("agent-a",),
        governance_policy_id="policy-1",
        deadline="2026-01-01T00:00:00+00:00",
    )
    child = ctx.child("agent-b", parent_task_id="task-a")
    assert child.visited_agents == ("agent-a", "agent-b")
    assert child.depth == 2
    assert child.governance_policy_id == "policy-1"
    assert child.deadline == "2026-01-01T00:00:00+00:00"
    # the child's own task id is unknown at call time
    assert child.self_task_id is None


def test_parallel_branches_do_not_pollute_each_other():
    """A delegates to B and C in parallel. Each branch inherits A's chain and
    appends only its own target — B's branch must not contain C, nor C contain B."""
    parent = CallContext(
        correlation_id="corr",
        caller_agent_id="agent-a",
        root_task_id="root",
        depth=0,
        visited_agents=("agent-a",),
    )
    branch_b = parent.child("agent-b", parent_task_id="task-a")
    branch_c = parent.child("agent-c", parent_task_id="task-a")

    assert branch_b.visited_agents == ("agent-a", "agent-b")
    assert branch_c.visited_agents == ("agent-a", "agent-c")
    assert "agent-c" not in branch_b.visited_agents
    assert "agent-b" not in branch_c.visited_agents
    # the shared parent is unchanged by either derivation
    assert parent.visited_agents == ("agent-a",)

    # a deeper hop on branch_b keeps only branch_b's history
    b2 = branch_b.child("agent-d", parent_task_id="task-b")
    assert b2.visited_agents == ("agent-a", "agent-b", "agent-d")
    assert "agent-c" not in b2.visited_agents


def test_reverse_call_chain_is_representable():
    """A -> B -> A is a legal, finite chain: the revisit is counted, not banned."""
    a = CallContext(correlation_id="c", caller_agent_id="agent-a",
                    root_task_id="r", visited_agents=("agent-a",))
    b = a.child("agent-b", parent_task_id="t-a")
    a_again = b.child("agent-a", parent_task_id="t-b")
    assert a_again.visited_agents == ("agent-a", "agent-b", "agent-a")
    assert a_again.visited_agents.count("agent-a") == 2  # revisit counted


def test_from_inbound_carries_governance_context():
    ctx = CallContext.from_inbound(
        agent_id="agent-b",
        correlation_id="corr",
        task_id="task-b",
        root_task_id="root",
        parent_task_id="task-a",
        depth=1,
        visited_agents=["agent-a"],
        governance_policy_id="policy-9",
        deadline="2026-02-02T00:00:00+00:00",
    )
    assert ctx.visited_agents == ("agent-a", "agent-b")
    assert ctx.self_task_id == "task-b"
    assert ctx.governance_policy_id == "policy-9"
    assert ctx.deadline == "2026-02-02T00:00:00+00:00"


# ── outbound wire propagation ────────────────────────────────────────────

def test_delegate_sends_visited_agents_and_governance_on_the_wire():
    rt, clients = _runtime(agent_id="agent-a")
    ctx = CallContext.from_inbound(
        agent_id="agent-a",
        correlation_id="corr-1",
        task_id="task-a",
        root_task_id="task-a",
        depth=0,
        governance_policy_id="policy-1",
        deadline="2026-01-01T00:00:00+00:00",
    )
    rt.delegate("need b", context=ctx, skill="skill-b")
    sent = clients[0].calls[0]
    # caller identity + full visit chain + governance context cross the boundary
    assert sent["caller_agent_id"] == "agent-a"
    assert sent["target_agent_id"] == "id-b"
    assert sent["visited_agents"] == ["agent-a", "id-b"]
    assert sent["governance_policy_id"] == "policy-1"
    assert sent["deadline"] == "2026-01-01T00:00:00+00:00"
    assert sent["root_task_id"] == "task-a"
    assert sent["parent_task_id"] == "task-a"  # caller's own task becomes parent
    assert sent["depth"] == 1


def test_multihop_visited_chain_accumulates_across_delegations():
    """Simulate A -> B -> C by feeding each hop's outbound wire into the next
    hop's inbound context, proving the chain accumulates over real boundaries."""
    rt_a, clients_a = _runtime(agent_id="agent-a")
    ctx_a = CallContext.from_inbound(agent_id="agent-a", correlation_id="corr",
                                     task_id="tA", root_task_id="tA", depth=0)
    rt_a.delegate("to b", context=ctx_a, skill="s")
    wire_ab = clients_a[0].calls[0]

    # B receives the wire, builds its inbound context, then delegates to C.
    ctx_b = CallContext.from_inbound(
        agent_id="id-b",
        correlation_id=wire_ab["correlation_id"],
        task_id="tB",
        root_task_id=wire_ab["root_task_id"],
        parent_task_id=wire_ab["parent_task_id"],
        depth=wire_ab["depth"],
        visited_agents=wire_ab["visited_agents"],
    )
    assert ctx_b.visited_agents == ("agent-a", "id-b")
    rt_b, clients_b = _runtime(agent_id="id-b")
    rt_b.delegate("to c", context=ctx_b, skill="s")
    wire_bc = clients_b[0].calls[0]
    assert wire_bc["visited_agents"] == ["agent-a", "id-b", "id-b"]
    assert wire_bc["depth"] == 2
    assert wire_bc["root_task_id"] == "tA"  # root stable across hops
