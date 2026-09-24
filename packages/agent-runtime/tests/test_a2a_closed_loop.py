"""A2A OS end-to-end acceptance: autonomous Agent-to-Agent collaboration.

These tests prove the acceptance closed loop *without a central orchestrator*:

    User -> Agent A -> (discover/route via OS) -> Agent B
         -> Agent B autonomously decides it needs more capability
         -> (discover/route via OS) -> Agent C
         -> C returns to B -> B returns to A -> A returns to User

The "OS" here is only discovery/routing/graph infrastructure; the Agents own
every decision to delegate. Lineage (correlation/root/parent/depth) propagates,
the runtime graph records each edge, and governance bounds recursion.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from agent_runtime.a2a_server import inbound_context, jsonrpc_error, jsonrpc_result
from agent_runtime.collaboration import (
    A2ACollaborationRuntime,
    GovernanceConfig,
    GovernanceError,
    RECURSION_LIMIT_EXCEEDED,
)


# ── Fake A2A OS: discovery / routing / runtime graph only ────────────────


class FakeOS:
    def __init__(self):
        self.registry: dict[str, dict] = {}  # skill -> agent descriptor
        self.edges: list[dict] = []

    def register(self, skill, *, agent_id, agent_key, endpoint):
        self.registry[skill] = {
            "agent_id": agent_id,
            "agent_key": agent_key,
            "endpoint": endpoint,
            "status": "online",
            "score": 0.9,
            "skills": [skill],
        }

    def _select(self, payload):
        skills = list(payload.get("required_skills") or [])
        if payload.get("skill"):
            skills.insert(0, payload["skill"])
        exclude = set(payload.get("exclude_agent_ids") or [])
        for s in skills:
            agent = self.registry.get(s)
            if agent and agent["agent_id"] not in exclude and agent["agent_key"] not in exclude:
                return {"selected_agent": agent, "candidates": [agent]}
        return {"selected_agent": None, "candidates": []}

    def transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            payload = {}
            if request.content:
                import json as _json

                payload = _json.loads(request.content)
            if request.url.path in ("/v1/route", "/v1/discover"):
                return httpx.Response(200, json=self._select(payload))
            if request.url.path == "/v1/runtime/edges":
                self.edges.append(payload)
                return httpx.Response(201, json={"ok": True, **payload})
            return httpx.Response(404, json={"error": "not found"})

        return httpx.MockTransport(handler)


# ── In-process Agents (each is Server + Client) ──────────────────────────


class BaseAgent:
    skill = "base"

    def __init__(self, os: FakeOS, *, governance=None):
        self.agent_id = f"id-{self.skill}"
        self.endpoint = f"http://{self.skill}:8000/"
        self.runtime = A2ACollaborationRuntime(
            agent_id=self.agent_id,
            os_base_url="http://os:8080",
            governance=governance or GovernanceConfig(),
            http_transport=os.transport(),
            a2a_client_factory=lambda ep, to: FakeA2AClient(ep, to, _dispatch),
        )

    def text_of(self, task) -> str:
        for a in task.get("artifacts", []):
            for p in a.get("parts", []):
                if p.get("type") == "text" and p.get("text"):
                    return p["text"]
        return ""

    def _task(self, text, task_id):
        return {
            "id": task_id,
            "status": "completed",
            "artifacts": [{"name": "out", "parts": [{"type": "text", "text": text}]}],
        }

    def handle(self, text, params):
        task_id = str(uuid.uuid4())
        ctx = inbound_context(params, agent_id=self.agent_id, task_id=task_id)
        return self._task(self.run(text, ctx, task_id), task_id)

    def run(self, text, ctx, task_id):  # pragma: no cover - overridden
        raise NotImplementedError


class RagAgent(BaseAgent):
    skill = "knowledge-search"

    def run(self, text, ctx, task_id):
        return f"KB[citations for: {text.strip()[:40]}]"


class AnalysisAgent(BaseAgent):
    skill = "business-analysis"

    def run(self, text, ctx, task_id):
        # Autonomous decision: analysis needs grounding -> discover a RAG peer.
        knowledge = ""
        if "needs-knowledge" in text and ctx.depth < self.runtime.governance.max_delegation_depth:
            res = self.runtime.delegate(
                f"{text} (grounding query)",
                context=ctx,
                skill="knowledge-search",
                self_task_id=task_id,
            )
            knowledge = self.text_of(res.task if isinstance(res.task, dict) else {})
        return f"ANALYSIS[{text.strip()[:30]} | grounded={knowledge or 'none'}]"


class ResearchAgent(BaseAgent):
    skill = "web-research"

    def run(self, text, ctx, task_id):
        res = self.runtime.delegate(
            text,
            context=ctx,
            skill="business-analysis",
            self_task_id=task_id,
        )
        inner = self.text_of(res.task if isinstance(res.task, dict) else {})
        return f"RESEARCH[{inner}]"


class EchoAgent(BaseAgent):
    """Generic peer used for reverse-call / fan-out tests."""

    def __init__(self, os, skill="echo", *, delegate_to=None, governance=None):
        self.skill = skill
        super().__init__(os, governance=governance)
        self.delegate_to = delegate_to

    def run(self, text, ctx, task_id):
        if self.delegate_to and ctx.depth < self.runtime.governance.max_delegation_depth:
            res = self.runtime.delegate(
                text, context=ctx, skill=self.delegate_to, self_task_id=task_id
            )
            inner = self.text_of(res.task if isinstance(res.task, dict) else {})
            return f"{self.skill.upper()}[{inner}]"
        return f"{self.skill.upper()}[{text.strip()[:20]}]"


class FakeA2AClient:
    def __init__(self, endpoint, timeout, dispatch):
        self.endpoint = endpoint
        self.timeout = timeout
        self._dispatch = dispatch

    def send_text(self, text, *, skill_id=None, correlation_id=None,
                  parent_task_id=None, root_task_id=None, depth=0,
                  caller_agent_id=None, target_agent_id=None,
                  visited_agents=None, governance_policy_id=None, deadline=None,
                  idempotency_key=None, callback_url=None):
        params = {
            "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
            "correlationId": correlation_id,
            "parentTaskId": parent_task_id,
            "rootTaskId": root_task_id,
            "depth": depth,
            "callerAgentId": caller_agent_id,
            "targetAgentId": target_agent_id,
            "visitedAgents": list(visited_agents or []),
            "governancePolicyId": governance_policy_id,
            "deadline": deadline,
            "idempotencyKey": idempotency_key,
            "callbackUrl": callback_url,
            "metadata": {"skillId": skill_id},
        }
        return self._dispatch(self.endpoint, text, params)


# Endpoint -> agent instance, populated per test.
DISPATCH: dict[str, BaseAgent] = {}


def _dispatch(endpoint, text, params):
    agent = DISPATCH.get(endpoint)
    if agent is None:
        raise AssertionError(f"no agent at endpoint {endpoint}")
    return agent.handle(text, params)


@pytest.fixture
def os_three():
    os_ = FakeOS()
    rag = RagAgent(os_)
    analysis = AnalysisAgent(os_)
    research = ResearchAgent(os_)
    os_.register("knowledge-search", agent_id=rag.agent_id, agent_key="rag", endpoint=rag.endpoint)
    os_.register("business-analysis", agent_id=analysis.agent_id, agent_key="analysis", endpoint=analysis.endpoint)
    os_.register("web-research", agent_id=research.agent_id, agent_key="research", endpoint=research.endpoint)
    DISPATCH.clear()
    DISPATCH.update({a.endpoint: a for a in (rag, analysis, research)})
    return os_, research, analysis, rag


def _user_call(agent, text):
    """Simulate a User invoking an Agent directly (root of the graph)."""
    root_task = "root-" + uuid.uuid4().hex[:8]
    params = {
        "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
        "correlationId": root_task,
        "rootTaskId": root_task,
        "depth": 0,
    }
    return agent.handle(text, params), root_task


# ── Test 5 / acceptance closed loop: A -> B -> C -> B -> A ───────────────


def test_closed_loop_autonomous_delegation(os_three):
    os_, research, analysis, rag = os_three
    task, root = _user_call(research, "research goal needs-knowledge about market")

    out = research.text_of(task)
    # Research(A) wrapped Analysis(B) which autonomously grounded via RAG(C).
    assert out.startswith("RESEARCH[ANALYSIS[")
    assert "grounded=KB[citations" in out

    # Runtime graph recorded both autonomous edges, with correct lineage.
    edges = os_.edges
    assert len(edges) == 2
    ab = next(e for e in edges if e["caller_agent_id"] == research.agent_id)
    bc = next(e for e in edges if e["caller_agent_id"] == analysis.agent_id)
    assert ab["target_agent_id"] == analysis.agent_id
    assert bc["target_agent_id"] == rag.agent_id
    assert ab["depth"] == 1 and bc["depth"] == 2
    assert ab["correlation_id"] == root and bc["correlation_id"] == root
    assert bc["parent_task_id"]  # B's own task became C's parent


# ── Test 1: A -> B ───────────────────────────────────────────────────────


def test_single_hop_delegation(os_three):
    os_, research, analysis, rag = os_three
    task, root = _user_call(research, "plain research goal")
    out = research.text_of(task)
    assert out.startswith("RESEARCH[ANALYSIS[")
    assert "grounded=none" in out  # analysis chose NOT to delegate
    assert len(os_.edges) == 1
    assert os_.edges[0]["caller_agent_id"] == research.agent_id


# ── Test 3: A -> B -> A (reverse call) ───────────────────────────────────


def test_reverse_call_within_governance():
    os_ = FakeOS()
    # a1 delegates to b, b delegates back to a2 (a terminal echo) to avoid a loop.
    a = EchoAgent(os_, skill="a", delegate_to="b-skill")
    b = EchoAgent(os_, skill="b", delegate_to="a-skill")
    a_term = EchoAgent(os_, skill="a", )  # terminal A (no delegate)
    a_term.skill = "a"
    # Register: b-skill -> b ; a-skill -> a_term (the reverse target)
    os_.register("b-skill", agent_id=b.agent_id, agent_key="b", endpoint=b.endpoint)
    os_.register("a-skill", agent_id="id-a-term", agent_key="a-term", endpoint="http://a-term:8000/")
    DISPATCH.clear()
    DISPATCH.update({a.endpoint: a, b.endpoint: b, "http://a-term:8000/": a_term})
    a_term.endpoint = "http://a-term:8000/"

    task, root = _user_call(a, "reverse test")
    out = a.text_of(task)
    assert out == "A[B[A[]]]" or out.startswith("A[B[A[")
    # Two autonomous edges: a->b and b->a(term)
    assert len(os_.edges) == 2


# ── Test 4: A -> B and A -> C (fan-out) ──────────────────────────────────


def test_fan_out_two_targets():
    os_ = FakeOS()
    root_agent = ResearchAgent.__new__(ResearchAgent)  # custom fan-out agent

    class Fan(BaseAgent):
        skill = "fan"

        def run(self, text, ctx, task_id):
            r1 = self.runtime.delegate(text, context=ctx, skill="b-skill", self_task_id=task_id)
            r2 = self.runtime.delegate(text, context=ctx, skill="c-skill", self_task_id=task_id)
            return f"FAN[{self.text_of(r1.task)}|{self.text_of(r2.task)}]"

    fan = Fan(os_)
    b = EchoAgent(os_, skill="b")
    c = EchoAgent(os_, skill="c")
    os_.register("b-skill", agent_id=b.agent_id, agent_key="b", endpoint=b.endpoint)
    os_.register("c-skill", agent_id=c.agent_id, agent_key="c", endpoint=c.endpoint)
    DISPATCH.clear()
    DISPATCH.update({fan.endpoint: fan, b.endpoint: b, c.endpoint: c})

    task, root = _user_call(fan, "fanout")
    out = fan.text_of(task)
    assert out.startswith("FAN[B[") and "|C[" in out
    assert len(os_.edges) == 2
    assert {e["target_agent_id"] for e in os_.edges} == {b.agent_id, c.agent_id}


# ── Test: governance bounds a runaway chain ──────────────────────────────


def test_governance_blocks_runaway_recursion():
    os_ = FakeOS()
    gov = GovernanceConfig(max_delegation_depth=1, max_agent_visits=99)

    class LoopAgent(BaseAgent):
        """Always delegates — relies on OS/runtime governance to stop the loop."""

        def __init__(self, os, skill, delegate_to):
            self.skill = skill
            super().__init__(os, governance=gov)
            self.delegate_to = delegate_to

        def run(self, text, ctx, task_id):
            res = self.runtime.delegate(
                text, context=ctx, skill=self.delegate_to, self_task_id=task_id
            )
            return f"{self.skill.upper()}[{self.text_of(res.task)}]"

    ping = LoopAgent(os_, "ping", "pong-skill")
    pong = LoopAgent(os_, "pong", "ping-skill")
    os_.register("pong-skill", agent_id=pong.agent_id, agent_key="pong", endpoint=pong.endpoint)
    os_.register("ping-skill", agent_id=ping.agent_id, agent_key="ping", endpoint=ping.endpoint)
    DISPATCH.clear()
    DISPATCH.update({ping.endpoint: ping, pong.endpoint: pong})

    with pytest.raises(GovernanceError) as ei:
        _user_call(ping, "loop")
    assert ei.value.code == RECURSION_LIMIT_EXCEEDED
