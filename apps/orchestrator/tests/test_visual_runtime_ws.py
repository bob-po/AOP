"""Visual Runtime WebSocket — connect, snapshot, events, sequence recovery."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

# Import app after ensuring memory execution store for hermetic tests
import os

os.environ.setdefault("EXECUTION_STORE", "memory")


@pytest.fixture
def client(monkeypatch):
    from execution import ExecutionService
    from execution.events import ExecutionEvent
    import main as main_mod
    from app_context import ctx

    svc = ExecutionService()
    monkeypatch.setattr(main_mod, "execution", svc)
    monkeypatch.setattr(ctx, "execution", svc, raising=False)

    # Minimal task get stub
    class _Tasks:
        def get(self, task_id, tenant_id=None):
            return {
                "id": task_id,
                "status": "running",
                "title": "ws-demo",
                "created_at": "2026-10-03T10:00:00Z",
            }

        def collaboration_graph_view(self, root_task_id):
            return {"nodes": [], "links": [], "kind": "collaboration_graph"}

    monkeypatch.setattr(ctx, "tasks", _Tasks(), raising=False)

    # Seed events
    svc.events.emit(
        ExecutionEvent(
            event_type="task.created",
            event_id="ws_1",
            task_id="ws-root",
            root_task_id="ws-root",
        )
    )
    svc.events.emit(
        ExecutionEvent(
            event_type="agent.started",
            event_id="ws_2",
            task_id="ws-root",
            root_task_id="ws-root",
            agent_id="agent-a",
        )
    )

    with TestClient(main_mod.app) as c:
        yield c, svc


def test_ws_snapshot_and_events(client):
    c, svc = client
    with c.websocket_connect("/ws/tasks/ws-root") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert msg["sequence"] >= 2
        assert msg["graph"]["task_id"] == "ws-root"
        assert any(
            e.get("event_type") in {"task.created", "agent.started"}
            for e in (msg.get("events") or [])
        )

        # emit live event
        from execution.events import ExecutionEvent

        svc.events.emit(
            ExecutionEvent(
                event_type="agent.completed",
                event_id="ws_3",
                task_id="ws-root",
                root_task_id="ws-root",
                agent_id="agent-a",
            )
        )
        # may receive event and/or graph
        got_event = False
        for _ in range(6):
            frame = ws.receive_json()
            if frame.get("type") == "event":
                assert frame["event"]["event_id"] == "ws_3"
                assert frame["sequence"] == 3
                got_event = True
                break
            if frame.get("type") == "ping":
                continue
        assert got_event


def test_http_graph_snapshot(client):
    c, _svc = client
    res = c.get("/v1/tasks/ws-root/graph")
    assert res.status_code == 200
    body = res.json()
    assert body["task_id"] == "ws-root"
    assert "nodes" in body and "edges" in body and "events" in body
    assert body["sequence"] >= 2


def test_sequence_no_duplicate_on_reconnect_semantics(client):
    c, svc = client
    # First connection consumes snapshot
    with c.websocket_connect("/v1/tasks/ws-root/visual/ws") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"
        last = snap["sequence"]
        from execution.events import ExecutionEvent

        # Re-emit same id — bus is idempotent; client must not see new seq
        svc.events.emit(
            ExecutionEvent(
                event_type="agent.started",
                event_id="ws_2",
                task_id="ws-root",
                root_task_id="ws-root",
                agent_id="agent-a",
            )
        )
        svc.events.emit(
            ExecutionEvent(
                event_type="tool.called",
                event_id="ws_tool",
                task_id="ws-root",
                root_task_id="ws-root",
                agent_id="agent-a",
                payload={"tool": "search"},
            )
        )
        frame = None
        for _ in range(8):
            frame = ws.receive_json()
            if frame.get("type") == "event":
                break
        assert frame is not None
        assert frame["type"] == "event"
        assert frame["event"]["event_id"] == "ws_tool"
        assert frame["sequence"] == last + 1
