"""Harness peer-approval inbox and OS callback."""

from __future__ import annotations

import pytest

from agent_runtime.harness.adapter import create_harness_app
from agent_runtime.harness.approvals import parse_approval_decision
from agent_runtime.harness.protocol import (
    HarnessEvent,
    HarnessEventType,
    HarnessResult,
    HarnessStatus,
    TokenUsage,
)

CARD = {
    "name": "Mock Harness",
    "url": "http://127.0.0.1:9999/",
    "version": "0.0.1",
    "protocolVersion": "0.3.0",
    "preferredTransport": "JSONRPC",
    "capabilities": {"streaming": True, "pushNotifications": False},
    "skills": [{"id": "code-assist", "name": "Code Assist", "tags": ["code"]}],
}


class MockRunner:
    def __init__(self) -> None:
        self.runs = 0

    async def run(self, *, task_id, message, skill_id, on_event):
        self.runs += 1
        await on_event(
            HarnessEvent(
                type=HarnessEventType.STATUS,
                task_id=task_id,
                timestamp="2026-01-01T00:00:00Z",
                payload={"state": "working"},
            )
        )
        return HarnessResult(
            text="hello",
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=TokenUsage(input_tokens=1, output_tokens=1, model="mock"),
        )


def test_parse_approval_decision_json_and_fence():
    assert parse_approval_decision('{"approved": true, "reason": "ok"}') == {
        "approved": True,
        "reason": "ok",
    }
    fenced = 'Sure.\n```json\n{"approved": false, "reason": "risk"}\n```\n'
    assert parse_approval_decision(fenced) == {"approved": False, "reason": "risk"}
    assert parse_approval_decision("I approve this hop.")["approved"] is True
    assert parse_approval_decision("reject: missing tests")["approved"] is False


@pytest.fixture
def approval_client(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.setenv("HARNESS_APPROVAL_REVIEW", "0")
    monkeypatch.setenv("A2A_OS_URL", "http://os.test")
    monkeypatch.delenv("AOP_COLLAB_TOKEN", raising=False)
    runner = MockRunner()
    app = create_harness_app(
        agent_id="claude-code",
        runner=runner,
        card=CARD,
        enable_heartbeat=False,
    )
    return TestClient(app), runner


def test_health_advertises_peer_approval(approval_client):
    tc, _ = approval_client
    body = tc.get("/health").json()
    assert body["peer_approval"] is True
    assert body["pending_approvals"] == 0


def test_receive_queue_and_manual_callback(approval_client, monkeypatch):
    tc, runner = approval_client
    calls: list[tuple[str, dict]] = []

    class _Resp:
        status_code = 200
        text = "{}"

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls.append((url, json or {}))
        return _Resp()

    monkeypatch.setattr("httpx.post", fake_post)

    r = tc.post(
        "/v1/approvals",
        json={
            "type": "approval_request",
            "task_id": "t-1",
            "node_key": "hop-a",
            "approval_mode": "agent",
            "approver_agent": "claude-code",
            "reason": "peer review",
        },
    )
    assert r.status_code == 202
    rec = r.json()
    assert rec["status"] == "pending"
    assert rec["task_id"] == "t-1"
    assert runner.runs == 0

    listed = tc.get("/v1/approvals?status=pending").json()
    assert listed["count"] == 1

    decided = tc.post(
        f"/v1/approvals/{rec['id']}/decide",
        json={"approved": True, "reason": "looks good"},
    )
    assert decided.status_code == 200
    body = decided.json()
    assert body["status"] == "approved"
    assert body["callback"]["ok"] is True
    assert calls[0][0] == "http://os.test/v1/tasks/t-1/approve"
    assert calls[0][1]["actor"] == "agent"
    assert calls[0][1]["node_key"] == "hop-a"


def test_auto_review_approves_via_runner(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    class ReviewRunner(MockRunner):
        async def run(self, *, task_id, message, skill_id, on_event):
            self.runs += 1
            assert skill_id == "peer-approval"
            text = message["parts"][0]["text"]
            assert "designated peer approver" in text
            return HarnessResult(
                text='{"approved": true, "reason": "safe"}',
                status=HarnessStatus.OK,
                skill_id=skill_id,
            )

    monkeypatch.setenv("HARNESS_APPROVAL_REVIEW", "1")
    monkeypatch.setenv("HARNESS_APPROVAL_SYNC", "1")
    monkeypatch.setenv("A2A_OS_URL", "http://os.test")
    monkeypatch.delenv("AOP_COLLAB_TOKEN", raising=False)

    class _Resp:
        status_code = 200
        text = "{}"

    calls: list[str] = []

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        calls.append(url)
        return _Resp()

    monkeypatch.setattr("httpx.post", fake_post)

    app = create_harness_app(
        agent_id="claude-code",
        runner=ReviewRunner(),
        card=CARD,
        enable_heartbeat=False,
    )
    tc = TestClient(app)
    rec = tc.post(
        "/v1/approvals",
        json={"task_id": "t-2", "node_key": "n1", "reason": "gate"},
    ).json()
    assert rec["status"] == "approved"
    assert rec["decision_reason"] == "safe"
    assert calls == ["http://os.test/v1/tasks/t-2/approve"]


def test_reject_callback_path(approval_client, monkeypatch):
    tc, _ = approval_client

    class _Resp:
        status_code = 200
        text = "{}"

    captured: list[tuple[str, dict]] = []

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        captured.append((url, json or {}))
        return _Resp()

    monkeypatch.setattr("httpx.post", fake_post)
    rec = tc.post("/v1/approvals", json={"task_id": "t-3", "node_key": "n"}).json()
    out = tc.post(
        f"/v1/approvals/{rec['id']}/decide",
        json={"approved": False, "reason": "unsafe"},
    ).json()
    assert out["status"] == "rejected"
    assert captured[0][0] == "http://os.test/v1/tasks/t-3/reject"
    assert captured[0][1]["actor"] == "agent"
    assert captured[0][1]["reason"] == "unsafe"
