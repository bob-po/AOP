"""Callback SSRF + control-plane helpers (tasks/subscribe removed)."""

from __future__ import annotations

from agent_runtime.a2a_server import (
    extract_lineage,
    format_sse_frame,
    handle_control_method,
    notify_callback,
)


def test_extract_lineage_includes_callback_and_idempotency():
    lin = extract_lineage(
        {
            "message": {
                "callbackUrl": "http://cb/hook",
                "idempotencyKey": "ik-1",
                "visitedAgents": ["a", "b"],
            },
            "rootTaskId": "root",
        }
    )
    assert lin["callback_url"] == "http://cb/hook"
    assert lin["idempotency_key"] == "ik-1"
    assert lin["visited_agents"] == ["a", "b"]
    assert lin["root_task_id"] == "root"


def test_format_sse_frame():
    frame = format_sse_frame("status", {"taskId": "t1", "status": "completed"})
    assert frame.startswith(b"event: status\n")
    assert b"taskId" in frame
    assert frame.endswith(b"\n\n")


def test_handle_control_subscribe_removed():
    tasks = {"t1": {"id": "t1", "status": {"state": "completed"}}}
    body = handle_control_method(
        "tasks/subscribe",
        {"id": "t1"},
        req_id="1",
        tasks=tasks,
        subscribe_timeout_s=1.0,
    )
    assert body["error"]["code"] == -32601
    assert "subscribe" in body["error"]["message"]


def test_handle_control_delegate_removed():
    body = handle_control_method(
        "tasks/delegate",
        {"taskId": "t1", "targetAgentId": "x"},
        req_id="2",
        tasks={},
    )
    assert body["error"]["code"] == -32601


def test_notify_callback_best_effort_false_on_bad_url():
    assert notify_callback(None, {"id": "x"}) is False
    assert notify_callback("http://127.0.0.1:1/nope", {"id": "x"}, timeout=0.2) is False


def test_notify_callback_blocks_metadata_url(monkeypatch):
    monkeypatch.delenv("AOP_CALLBACK_ALLOW_PRIVATE", raising=False)
    assert notify_callback("http://169.254.169.254/latest", {"id": "x"}) is False
    assert notify_callback("file:///etc/passwd", {"id": "x"}) is False
