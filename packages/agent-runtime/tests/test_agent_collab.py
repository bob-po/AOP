"""Tests for the shared AgentCollaborator (agent client half)."""

from __future__ import annotations

from agent_runtime.agent_collab import AgentCollaborator
from agent_runtime.collaboration import CallContext


class FakeResult:
    def __init__(self, text):
        self.task = {"artifacts": [{"parts": [{"type": "text", "text": text}]}]}


class FakeRuntime:
    def __init__(self, text="PEER"):
        self.text = text
        self.calls = []

    def delegate(self, goal, *, context, skill=None, required_skills=None, **kw):
        self.calls.append({"goal": goal, "skill": skill, "required_skills": required_skills})
        return FakeResult(self.text)


def test_disabled_when_no_os_url(monkeypatch):
    monkeypatch.delenv("A2A_OS_URL", raising=False)
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    monkeypatch.delenv("A2A_AUTONOMOUS", raising=False)
    c = AgentCollaborator(agent_id="rag-agent", delegate_skill="x")
    assert c.available is False
    assert c.enabled() is False
    assert c.runtime() is None
    ctx = CallContext(correlation_id="c", caller_agent_id="rag-agent")
    assert c.fetch("goal", ctx) is None


def test_fetch_returns_peer_text_when_enabled():
    fake = FakeRuntime("GROUNDED")
    c = AgentCollaborator(agent_id="report-agent", delegate_skill="business-analysis", runtime=fake)
    c._enabled_override = True
    ctx = CallContext(correlation_id="c", caller_agent_id="report-agent")
    out = c.fetch("write report", ctx)
    assert out == "GROUNDED"
    assert fake.calls[0]["skill"] == "business-analysis"


def test_fetch_noop_without_delegate_skill():
    fake = FakeRuntime()
    c = AgentCollaborator(agent_id="image-agent", delegate_skill=None, runtime=fake)
    c._enabled_override = True
    ctx = CallContext(correlation_id="c", caller_agent_id="image-agent")
    assert c.fetch("draw", ctx) is None
    assert fake.calls == []


def test_fetch_noop_without_context():
    fake = FakeRuntime()
    c = AgentCollaborator(agent_id="code-agent", delegate_skill="x", runtime=fake)
    c._enabled_override = True
    assert c.fetch("run", None) is None


def test_fetch_swallows_errors():
    class Boom:
        def delegate(self, *a, **k):
            raise RuntimeError("network down")

    c = AgentCollaborator(agent_id="a", delegate_skill="s", runtime=Boom())
    c._enabled_override = True
    ctx = CallContext(correlation_id="c", caller_agent_id="a")
    assert c.fetch("goal", ctx) is None


def test_extract_text_dict_and_none():
    assert AgentCollaborator.extract_text({"artifacts": [{"parts": [{"type": "text", "text": "hi"}]}]}) == "hi"
    assert AgentCollaborator.extract_text({"artifacts": []}) is None
    assert AgentCollaborator.extract_text(None) is None


def test_cancel_helper():
    store = {"t1": {"id": "t1", "status": {"state": "completed"}}}
    c = AgentCollaborator(agent_id="a")
    ok, task = c.cancel(store, "t1")
    assert ok and task["status"]["state"] == "canceled"
    assert c.cancel(store, "missing")[0] is False


def test_context_builds_lineage():
    c = AgentCollaborator(agent_id="rag-agent", os_url="http://os:8080")
    ctx = c.context(
        {"correlationId": "corr", "rootTaskId": "root", "parentTaskId": "p", "depth": 2},
        task_id="t-self",
    )
    assert ctx.correlation_id == "corr"
    assert ctx.root_task_id == "root"
    assert ctx.depth == 2
    assert ctx.caller_agent_id == "rag-agent"
