"""Inbound/outbound interop against a local harness (official-shaped wire)."""

from __future__ import annotations

import json

import pytest

from a2a_sdk import A2AClient, AgentCard, Message, Part, Task, TaskStatus
from a2a_sdk.protocol import PROTOCOL_VERSION


@pytest.fixture
def harness_app(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from agent_runtime.harness.adapter import create_harness_app
    from agent_runtime.harness.protocol import (
        HarnessEvent,
        HarnessEventType,
        HarnessResult,
        HarnessStatus,
        TokenUsage,
    )

    class MockRunner:
        async def run(self, *, task_id, message, skill_id, on_event):
            await on_event(
                HarnessEvent(
                    type=HarnessEventType.DELTA,
                    task_id=task_id,
                    timestamp="2026-01-01T00:00:00Z",
                    payload={"text": "pong"},
                )
            )
            return HarnessResult(
                text="pong",
                status=HarnessStatus.OK,
                skill_id=skill_id or "default",
                usage=TokenUsage(input_tokens=1, output_tokens=1, model="mock"),
            )

        async def cancel(self, task_id: str) -> bool:
            return True

    monkeypatch.delenv("A2A_OS_URL", raising=False)
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    card = {
        "name": "Interop Agent",
        "description": "compliance harness",
        "url": "http://testserver/",
        "version": "0.1.0",
        "protocolVersion": PROTOCOL_VERSION,
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [{"id": "echo", "name": "Echo", "description": "echo"}],
    }
    app = create_harness_app(
        agent_id="interop",
        runner=MockRunner(),
        card=card,
        enable_heartbeat=False,
    )
    return TestClient(app)


def test_inbound_official_client_send_get(harness_app, monkeypatch):
    """Simulate an external A2A client: Card → message/send → tasks/get."""
    tc = harness_app

    # Card discovery (inbound)
    card_raw = tc.get("/.well-known/agent-card.json").json()
    card = AgentCard.from_dict(card_raw)
    assert card.protocol_version == PROTOCOL_VERSION
    assert card.preferred_transport == "JSONRPC"
    assert card.supports_streaming() is True

    # Official-shaped message/send (kind discriminator)
    body = {
        "jsonrpc": "2.0",
        "id": "ext-1",
        "method": "message/send",
        "params": {
            "id": "task-ext-1",
            "message": {
                "role": "user",
                "messageId": "m1",
                "parts": [{"kind": "text", "text": "hello"}],
                "metadata": {"skillId": "echo", "correlationId": "c1"},
            },
            "metadata": {"skillId": "echo", "correlationId": "c1"},
        },
    }
    result = tc.post("/", json=body).json()["result"]
    task = Task.from_dict(result)
    assert task.id == "task-ext-1"
    assert task.status == TaskStatus.COMPLETED
    assert task.artifacts[0].parts[0].kind == "text"

    got = tc.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": "ext-2",
            "method": "tasks/get",
            "params": {"id": "task-ext-1"},
        },
    ).json()["result"]
    assert got["id"] == "task-ext-1"
    assert got["status"]["state"] == "completed"


def test_outbound_sdk_against_harness(harness_app, monkeypatch):
    """Orchestrator-style outbound: A2AClient against harness via httpx transport."""
    tc = harness_app

    import httpx
    from a2a_sdk.client import A2AClient as Client

    class _Transport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            path = request.url.path
            method = request.method
            if method == "GET" and path.endswith("agent-card.json"):
                data = tc.get("/.well-known/agent-card.json").json()
                return httpx.Response(200, json=data)
            if method == "POST":
                body = json.loads(request.content.decode("utf-8"))
                r = tc.post("/", json=body)
                return httpx.Response(r.status_code, json=r.json(), headers=dict(r.headers))
            return httpx.Response(404)

    # Patch Client._rpc / fetch to use TestClient via monkeypatch of httpx.Client
    real_client_cls = httpx.Client

    def factory(*args, **kwargs):
        kwargs = dict(kwargs)
        kwargs["transport"] = _Transport()
        kwargs.pop("follow_redirects", None)
        return real_client_cls(*args, follow_redirects=True, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)

    client = Client("http://testserver/", timeout=10.0)
    assert client.card.name == "Interop Agent"
    task = client.send_text("hi", skill_id="echo", task_id="out-1")
    assert task.status == TaskStatus.COMPLETED
    text = task.artifacts[0].text() if task.artifacts else ""
    assert "pong" in text
