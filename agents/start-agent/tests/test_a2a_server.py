"""A2A OS: Start Agent as Server + Client (lineage, control plane, cancel)."""

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
    return client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "1", "method": "message/send", "params": params},
    )


def test_message_send_still_works_without_os(client):
    test_client, agent = client
    resp = _send(test_client, "Deploy ./demo --mode docker")
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert result["status"]["state"] == "completed"
    assert "autonomous_delegation" not in result["metadata"]
    data = result["artifacts"][0]["parts"][1]["data"]
    assert data["mode"] == "docker"


def test_tasks_cancel(client):
    test_client, agent = client
    task_id = _send(test_client, "plan only").json()["result"]["id"]
    resp = test_client.post(
        "/",
        json={"jsonrpc": "2.0", "id": "2", "method": "tasks/cancel", "params": {"id": task_id}},
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"]["state"] == "canceled"


def test_inbound_lineage_accepted(client):
    test_client, agent = client
    resp = _send(
        test_client,
        "analyze ./app",
        correlationId="corr-1",
        rootTaskId="root-1",
        parentTaskId="parent-1",
        depth=1,
        visitedAgents=["search-agent"],
    )
    assert resp.status_code == 200
    assert resp.json()["result"]["status"]["state"] == "completed"


def test_tasks_subscribe_snapshot(client):
    test_client, agent = client
    task_id = _send(test_client, "subscribe me").json()["result"]["id"]
    resp = test_client.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "3",
            "method": "tasks/subscribe",
            "params": {"id": task_id},
        },
    )
    assert resp.status_code == 200
    body = resp.json()["result"]
    assert body["count"] >= 1
    assert any(e.get("event") in {"status", "final"} for e in body["events"])


def test_idempotency_dedupes(client):
    test_client, agent = client
    r1 = _send(test_client, "same", idempotencyKey="k-start-1")
    r2 = _send(test_client, "same", idempotencyKey="k-start-1")
    assert r1.json()["result"]["id"] == r2.json()["result"]["id"]
