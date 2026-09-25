"""Tests for harness A2A adapter (mock runner)."""

from __future__ import annotations

import pytest

from agent_runtime.harness.adapter import create_harness_app
from agent_runtime.harness.protocol import (
    HarnessEvent,
    HarnessEventType,
    HarnessResult,
    HarnessStatus,
    TokenUsage,
)


class MockRunner:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.canceled: list[str] = []
        self.runs = 0

    async def run(self, *, task_id, message, skill_id, on_event):
        self.runs += 1
        await on_event(
            HarnessEvent(
                type=HarnessEventType.STATUS,
                task_id=task_id,
                timestamp="2026-01-01T00:00:00Z",
                payload={"state": "working", "message": "go"},
            )
        )
        await on_event(
            HarnessEvent(
                type=HarnessEventType.DELTA,
                task_id=task_id,
                timestamp="2026-01-01T00:00:01Z",
                payload={"text": "hello "},
            )
        )
        await on_event(
            HarnessEvent(
                type=HarnessEventType.DELTA,
                task_id=task_id,
                timestamp="2026-01-01T00:00:02Z",
                payload={"text": "world"},
            )
        )
        if self.fail:
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error="boom",
                skill_id=skill_id,
            )
        return HarnessResult(
            text="hello world",
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=TokenUsage(input_tokens=10, output_tokens=5, model="mock"),
            data={"echo": True},
        )

    async def cancel(self, task_id: str) -> bool:
        self.canceled.append(task_id)
        return True


CARD = {
    "name": "Mock Harness",
    "url": "http://127.0.0.1:9999/",
    "version": "0.0.1",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": True},
    "skills": [
        {"id": "code-assist", "name": "Code Assist", "tags": ["code"]},
    ],
}


@pytest.fixture
def client(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.delenv("A2A_OS_URL", raising=False)
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    runner = MockRunner()
    app = create_harness_app(
        agent_id="mock-harness",
        runner=runner,
        card=CARD,
        enable_heartbeat=False,
        system_prompt="You are mock.",
    )
    return TestClient(app), runner


def test_health_and_card(client):
    tc, _ = client
    r = tc.get("/health")
    assert r.status_code == 200
    assert r.json()["harness"] is True
    card = tc.get("/.well-known/agent-card.json").json()
    assert card["skills"][0]["id"] == "code-assist"


def test_message_send_artifacts_and_usage(client):
    tc, runner = client
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
            "metadata": {"skillId": "code-assist"},
        },
    }
    r = tc.post("/", json=body)
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["status"]["state"] == "completed"
    names = {a["name"] for a in result["artifacts"]}
    assert names == {"summary", "result"}
    assert result["metadata"]["usage"]["input_tokens"] == 10
    assert result["metadata"]["usage"]["output_tokens"] == 5
    assert runner.runs == 1
    data = result["artifacts"][1]["parts"][0]["data"]
    assert data["schemaVersion"] == "1.0"
    assert data["skillId"] == "code-assist"


def test_idempotency_cache(client):
    tc, runner = client
    body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "message/send",
        "params": {
            "idempotencyKey": "k1",
            "message": {"role": "user", "parts": [{"type": "text", "text": "once"}]},
            "metadata": {"skillId": "code-assist"},
        },
    }
    a = tc.post("/", json=body).json()["result"]
    b = tc.post("/", json=body).json()["result"]
    assert a["id"] == b["id"]
    assert runner.runs == 1


def test_unsupported_skill(client):
    tc, _ = client
    body = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "message/send",
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "x"}]},
            "metadata": {"skillId": "web-search"},
        },
    }
    r = tc.post("/", json=body).json()
    assert r["error"]["code"] == -32602


def test_tasks_cancel_invokes_runner(client):
    tc, runner = client
    send = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "message/send",
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "x"}]},
            "metadata": {"skillId": "code-assist"},
        },
    }
    task = tc.post("/", json=send).json()["result"]
    cancel = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tasks/cancel",
        "params": {"id": task["id"]},
    }
    r = tc.post("/", json=cancel)
    assert r.status_code == 200
    assert runner.canceled == [task["id"]]
    assert r.json()["result"]["status"]["state"] == "canceled"


def test_client_supplied_task_id(client):
    tc, _ = client
    body = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "message/send",
        "params": {
            "id": "os-chosen-id",
            "rootTaskId": "os-root",
            "correlationId": "os-root",
            "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
            "metadata": {"skillId": "code-assist"},
        },
    }
    result = tc.post("/", json=body).json()["result"]
    assert result["id"] == "os-chosen-id"
    assert result["rootTaskId"] == "os-root"


def test_cancel_by_root_task_id(client):
    """OS cancels with OS task id; adapter matches rootTaskId and kills runner."""
    tc, runner = client
    send = {
        "jsonrpc": "2.0",
        "id": 8,
        "method": "message/send",
        "params": {
            "id": "a2a-1",
            "rootTaskId": "os-task-99",
            "correlationId": "os-task-99",
            "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
            "metadata": {"skillId": "code-assist"},
        },
    }
    task = tc.post("/", json=send).json()["result"]
    assert task["id"] == "a2a-1"

    cancel = tc.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tasks/cancel",
            "params": {"id": "os-task-99"},
        },
    ).json()
    assert cancel["result"]["status"]["state"] == "canceled"
    assert "a2a-1" in runner.canceled


def test_failed_runner(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.delenv("A2A_OS_URL", raising=False)
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    app = create_harness_app(
        agent_id="mock-fail",
        runner=MockRunner(fail=True),
        card=CARD,
        enable_heartbeat=False,
    )
    tc = TestClient(app)
    body = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "message/send",
        "params": {
            "message": {"role": "user", "parts": [{"type": "text", "text": "x"}]},
            "metadata": {"skillId": "code-assist"},
        },
    }
    result = tc.post("/", json=body).json()["result"]
    assert result["status"]["state"] == "failed"
