"""A2A OS: Analysis Agent as Server + Client.

Proves the real agent.py wiring:
* inbound lineage is parsed and autonomous peer delegation is invoked when the
  OS is configured (no central orchestrator);
* the autonomously-fetched knowledge is incorporated into the analysis result
  and recorded in task metadata;
* tasks/cancel is handled;
* when collaboration is disabled the Agent behaves exactly as before.
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    import agent
    importlib.reload(agent)
    return TestClient(agent.app), agent


def _send(client, text, **extra):
    params = {
        "message": {"role": "user", "parts": [{"type": "text", "text": text}]},
        **extra,
    }
    return client.post("/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": params})


def test_autonomous_delegation_grounds_analysis(client, monkeypatch):
    test_client, agent = client
    import collab

    monkeypatch.setattr(collab, "autonomous_enabled", lambda: True)
    monkeypatch.setattr(collab, "fetch_knowledge", lambda goal, ctx: "KB-GROUNDED-INTERNAL")

    resp = _send(
        test_client,
        "User goal: assess market for X",
        correlationId="corr-1",
        rootTaskId="root-1",
        depth=1,
    )
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"]["state"] == "completed"

    blob = "".join(
        p.get("text", "")
        for a in result["artifacts"]
        for p in a["parts"]
        if p.get("type") == "text"
    )
    data_blob = result["artifacts"]
    # The autonomously-fetched knowledge was folded into the analysis.
    assert any("KB-GROUNDED-INTERNAL" in str(a) for a in data_blob) or "KB-GROUNDED" in blob
    assert result["metadata"]["autonomous_delegation"]["skill"] == collab.KNOWLEDGE_SKILL
    assert result["metadata"]["autonomous_delegation"]["root_task_id"] == "root-1"
    assert result["metadata"]["autonomous_delegation"]["depth"] == 2


def test_disabled_collaboration_is_noop(client, monkeypatch):
    test_client, agent = client
    import collab

    monkeypatch.setattr(collab, "autonomous_enabled", lambda: False)
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        return "SHOULD-NOT-APPEAR"

    monkeypatch.setattr(collab, "fetch_knowledge", _boom)
    resp = _send(test_client, "User goal: plain analysis")
    assert resp.status_code == 200
    assert called["n"] == 0
    assert "autonomous_delegation" not in resp.json()["result"]["metadata"]


def test_tasks_cancel(client):
    test_client, agent = client
    resp = _send(test_client, "User goal: something to cancel")
    task_id = resp.json()["result"]["id"]
    cancel = test_client.post(
        "/", json={"jsonrpc": "2.0", "id": "2", "method": "tasks/cancel", "params": {"id": task_id}}
    )
    assert cancel.status_code == 200
    assert cancel.json()["result"]["status"]["state"] == "canceled"


def test_fetch_knowledge_extracts_text(monkeypatch):
    """collab.fetch_knowledge pulls the first text artifact from the peer task."""
    import collab

    class FakeResult:
        task = {"artifacts": [{"parts": [{"type": "text", "text": "PEER-ANSWER"}]}]}

    class FakeRuntime:
        def delegate(self, *a, **k):
            return FakeResult()

    monkeypatch.setattr(collab, "autonomous_enabled", lambda: True)
    monkeypatch.setattr(collab, "get_runtime", lambda: FakeRuntime())
    assert collab.fetch_knowledge("goal", ctx=None) == "PEER-ANSWER"
