"""Phase 2 — tasks/subscribe + callback helpers."""

from __future__ import annotations

from agent_runtime.a2a_server import (
    extract_lineage,
    handle_control_method,
    notify_callback,
    subscribe_events,
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


def test_subscribe_events_emits_final_for_completed_task():
    tasks = {
        "t1": {"id": "t1", "status": {"state": "completed"}, "artifacts": []},
    }
    events = list(subscribe_events(tasks, {"id": "t1"}, timeout_s=1.0))
    kinds = [e["event"] for e in events]
    assert "status" in kinds or "final" in kinds
    assert events[-1]["event"] == "final"
    assert events[-1]["status"] == "completed"


def test_handle_control_subscribe_returns_events():
    tasks = {"t1": {"id": "t1", "status": {"state": "completed"}}}
    body = handle_control_method(
        "tasks/subscribe",
        {"id": "t1"},
        req_id="1",
        tasks=tasks,
        subscribe_timeout_s=1.0,
    )
    assert body["result"]["count"] >= 1


def test_notify_callback_best_effort_false_on_bad_url():
    assert notify_callback(None, {"id": "x"}) is False
    assert notify_callback("http://127.0.0.1:1/nope", {"id": "x"}, timeout=0.2) is False
