"""Tests for async message/send and AgentCollaborator.spawn/join."""

from __future__ import annotations

import asyncio
import time

import pytest

from agent_runtime.agent_collab import AgentCollaborator
from agent_runtime.collaboration import CallContext, DelegationResult
from agent_runtime.harness.adapter import create_harness_app, wants_async_send
from agent_runtime.harness.protocol import (
    HarnessEvent,
    HarnessEventType,
    HarnessResult,
    HarnessStatus,
    TokenUsage,
)


class SlowMockRunner:
    def __init__(self, delay_s: float = 0.35):
        self.delay_s = delay_s
        self.runs = 0
        self.started = asyncio.Event()

    async def run(self, *, task_id, message, skill_id, on_event):
        self.runs += 1
        self.started.set()
        await on_event(
            HarnessEvent(
                type=HarnessEventType.STATUS,
                task_id=task_id,
                timestamp="2026-01-01T00:00:00Z",
                payload={"state": "working", "message": "slow"},
            )
        )
        await asyncio.sleep(self.delay_s)
        await on_event(
            HarnessEvent(
                type=HarnessEventType.DELTA,
                task_id=task_id,
                timestamp="2026-01-01T00:00:01Z",
                payload={"text": "done-slow"},
            )
        )
        return HarnessResult(
            text="done-slow",
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=TokenUsage(input_tokens=1, output_tokens=1, model="mock"),
        )

    async def cancel(self, task_id: str) -> bool:
        return True


CARD = {
    "name": "Mock Harness",
    "url": "http://127.0.0.1:9999/",
    "version": "0.0.1",
    "protocolVersion": "0.3.0",
    "capabilities": {"streaming": True},
    "skills": [{"id": "code-assist", "name": "Code Assist", "tags": ["code"]}],
}


def test_wants_async_send_flags():
    assert wants_async_send({"metadata": {"async": True}}) is True
    assert wants_async_send({"callbackUrl": "http://cb"}) is True
    assert wants_async_send({"metadata": {"skillId": "x"}}) is False


@pytest.fixture
def slow_client(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    monkeypatch.delenv("A2A_OS_URL", raising=False)
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    runner = SlowMockRunner(delay_s=0.4)
    app = create_harness_app(
        agent_id="mock-harness",
        runner=runner,
        card=CARD,
        enable_heartbeat=False,
    )
    with TestClient(app) as tc:
        yield tc, runner


def test_async_message_send_returns_before_completion(slow_client):
    tc, runner = slow_client
    t0 = time.monotonic()
    r = tc.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "id": "async-1",
                "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
                "metadata": {"skillId": "code-assist", "async": True},
            },
        },
    )
    elapsed = time.monotonic() - t0
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["id"] == "async-1"
    assert result["status"]["state"] in {"submitted", "working"}
    assert elapsed < 0.35  # must not wait for SlowMockRunner

    # Poll until completed
    deadline = time.monotonic() + 3.0
    final = None
    while time.monotonic() < deadline:
        got = tc.post(
            "/",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tasks/get",
                "params": {"id": "async-1"},
            },
        ).json()["result"]
        state = (got.get("status") or {}).get("state")
        if state == "completed":
            final = got
            break
        time.sleep(0.05)
    assert final is not None
    assert runner.runs == 1
    assert any(
        (a.get("name") == "summary")
        for a in (final.get("artifacts") or [])
    )


def test_callback_url_triggers_async_path(slow_client, monkeypatch):
    tc, _ = slow_client
    called = {"n": 0}

    def fake_notify(url, task, *, timeout=10.0):
        called["n"] += 1
        called["url"] = url
        called["state"] = (task.get("status") or {}).get("state")
        return True

    # after_complete → AgentCollaborator.after_complete → notify_callback
    monkeypatch.setattr(
        "agent_runtime.agent_collab.notify_callback",
        fake_notify,
    )

    r = tc.post(
        "/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "id": "async-cb",
                "callbackUrl": "http://127.0.0.1:9/cb",
                "message": {"role": "user", "parts": [{"type": "text", "text": "hi"}]},
                "metadata": {"skillId": "code-assist"},
            },
        },
    )
    assert r.json()["result"]["status"]["state"] in {"submitted", "working"}

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and called["n"] == 0:
        time.sleep(0.05)
    assert called["n"] >= 1
    assert called.get("state") == "completed"


def test_spawn_join_via_collaborator_and_http(slow_client):
    tc, _ = slow_client

    def _in_event_loop() -> bool:
        try:
            asyncio.get_running_loop()
            return True
        except RuntimeError:
            return False

    class FakeRuntime:
        def __init__(self):
            self.spawns = []
            self._n = 0

        def spawn(self, goal, *, context, skill=None, agent_key=None, **kw):
            self._n += 1
            child_id = f"child-{self._n}"
            self.spawns.append({"goal": goal, "agent_key": agent_key, "skill": skill})
            if _in_event_loop():
                # TestClient cannot nest from the ASGI event loop — seed store directly.
                body = {
                    "id": child_id,
                    "status": {"state": "completed"},
                    "artifacts": [
                        {
                            "name": "summary",
                            "parts": [{"type": "text", "text": f"ok:{goal}"}],
                        }
                    ],
                    "metadata": {},
                    "correlationId": context.correlation_id,
                    "rootTaskId": context.root_task_id,
                }
                tc.app.state.tasks[child_id] = body
            else:
                body = tc.post(
                    "/",
                    json={
                        "jsonrpc": "2.0",
                        "id": 99,
                        "method": "message/send",
                        "params": {
                            "id": child_id,
                            "message": {
                                "role": "user",
                                "parts": [{"type": "text", "text": goal}],
                            },
                            "metadata": {"skillId": "code-assist", "async": True},
                        },
                    },
                ).json()["result"]
            return DelegationResult(
                task=body,
                target_agent_id="mock-harness",
                target_endpoint="http://testserver",
                skill=skill or agent_key,
                depth=1,
                correlation_id=context.correlation_id,
                root_task_id=context.root_task_id,
                parent_task_id=context.parent_task_id,
            )

        def _extract_task_id(self, task):
            return task.get("id") if isinstance(task, dict) else getattr(task, "id", None)

        def _extract_status(self, task):
            if isinstance(task, dict):
                return (task.get("status") or {}).get("state") or "submitted"
            return "submitted"

        def join(self, endpoint, task_id, *, timeout_s=120.0, poll_interval_s=0.5):
            if _in_event_loop():
                return tc.app.state.tasks.get(task_id)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                got = tc.post(
                    "/",
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tasks/get",
                        "params": {"id": task_id},
                    },
                ).json()["result"]
                if (got.get("status") or {}).get("state") == "completed":
                    return got
                time.sleep(poll_interval_s)
            return None

    fake = FakeRuntime()
    collab = AgentCollaborator(agent_id="parent", runtime=fake)
    collab._enabled_override = True
    tc.app.state.collab = collab

    ctx = CallContext(
        correlation_id="c1",
        root_task_id="root-1",
        parent_task_id="parent-1",
        self_task_id="parent-1",
        caller_agent_id="parent",
    )
    spawned = collab.spawn("peer work", ctx, agent_key="mock-harness")
    assert spawned is not None
    assert spawned["task_id"] == "child-1"
    assert spawned["endpoint"] == "http://testserver"

    joined = collab.join(spawned["endpoint"], spawned["task_id"], timeout_s=3.0)
    assert joined is not None
    assert (joined.get("status") or {}).get("state") == "completed"

    r = tc.post(
        "/v1/collab/spawn",
        json={"goal": "via http", "agent_key": "mock-harness", "parent_task_id": "parent-1"},
    )
    assert r.status_code == 200
    handle = r.json()
    assert handle.get("task_id")

    r2 = tc.post(
        "/v1/collab/join",
        json={"endpoint": "http://testserver", "task_id": handle["task_id"], "timeout_s": 3},
    )
    assert r2.status_code == 200
    assert r2.json()["status"]["state"] == "completed"
