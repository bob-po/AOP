"""A2A OS: Report Agent as Server + Client (lineage, delegation, cancel)."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import agent
    importlib.reload(agent)
    return TestClient(agent.app), agent


def _send(client, text, **extra):
    params = {"message": {"role": "user", "parts": [{"type": "text", "text": text}]}, **extra}
    return client.post("/", json={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": params})


def test_message_send_still_works_without_os(client):
    test_client, agent = client
    resp = _send(test_client, "User goal: summarize the multi-agent architecture")
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"]["state"] == "completed"
    assert "autonomous_delegation" not in result["metadata"]


def test_tasks_cancel(client):
    test_client, agent = client
    task_id = _send(test_client, "User goal: cancel me").json()["result"]["id"]
    resp = test_client.post(
        "/", json={"jsonrpc": "2.0", "id": "2", "method": "tasks/cancel", "params": {"id": task_id}}
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"]["state"] == "canceled"


def test_tasks_cancel_unknown(client):
    test_client, _ = client
    resp = test_client.post(
        "/", json={"jsonrpc": "2.0", "id": "3", "method": "tasks/cancel", "params": {"id": "nope"}}
    )
    assert resp.json()["error"]["code"] == -32001


def test_autonomous_delegation_folds_into_metadata(client, monkeypatch):
    test_client, agent = client
    from agent_runtime.agent_collab import AgentCollaborator

    class FakeResult:
        task = {"artifacts": [{"parts": [{"type": "text", "text": "PEER-INSIGHT"}]}]}

    class FakeRuntime:
        def delegate(self, *a, **k):
            return FakeResult()

    collab = AgentCollaborator(agent_id="report-agent", delegate_skill="business-analysis", runtime=FakeRuntime())
    collab._enabled_override = True
    monkeypatch.setattr(agent, "_COLLAB", collab)

    resp = _send(test_client, "User goal: deep topic", correlationId="c1", rootTaskId="r1", depth=1)
    result = resp.json()["result"]
    assert result["metadata"]["autonomous_delegation"] == "PEER-INSIGHT"
