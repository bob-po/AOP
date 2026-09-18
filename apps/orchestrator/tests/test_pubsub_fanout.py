"""Pub/Sub fan-out tests (requires Redis)."""

from __future__ import annotations

import json
import os
import time

import pytest

from streams import CHANNEL_GLOBAL, StreamClient, task_events_channel


def _redis_ok() -> bool:
    try:
        c = StreamClient(redis_url=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"))
        c.r.ping()
        return True
    except Exception:
        return False


requires_redis = pytest.mark.skipif(not _redis_ok(), reason="Redis not reachable")


@requires_redis
def test_publish_task_event_fans_out_to_task_and_global():
    client = StreamClient()
    task_id = "00000000-0000-0000-0000-00000000abcd"
    pubsub_task = client.subscribe_task_events(task_id)
    pubsub_global = client.subscribe_global_events()
    # Drain subscribe acks
    time.sleep(0.05)
    pubsub_task.get_message(ignore_subscribe_messages=True, timeout=0.1)
    pubsub_global.get_message(ignore_subscribe_messages=True, timeout=0.1)

    try:
        msg_id = client.publish_task_event(
            "task.test.fanout",
            {"task_id": task_id, "node_key": "search"},
        )
        assert msg_id

        got_task = None
        got_global = None
        deadline = time.time() + 2.0
        while time.time() < deadline and (got_task is None or got_global is None):
            if got_task is None:
                m = pubsub_task.get_message(ignore_subscribe_messages=True, timeout=0.2)
                if m and m.get("type") == "message":
                    got_task = json.loads(m["data"])
            if got_global is None:
                m = pubsub_global.get_message(ignore_subscribe_messages=True, timeout=0.2)
                if m and m.get("type") == "message":
                    got_global = json.loads(m["data"])

        assert got_task is not None
        assert got_task["event_type"] == "task.test.fanout"
        assert got_task["task_id"] == task_id
        assert got_global is not None
        assert got_global["event_type"] == "task.test.fanout"
        assert task_events_channel(task_id).startswith("aop:task:")
        assert CHANNEL_GLOBAL == "aop:events"
    finally:
        pubsub_task.unsubscribe()
        pubsub_task.close()
        pubsub_global.unsubscribe()
        pubsub_global.close()


@requires_redis
def test_two_subscribers_both_receive():
    """Competing consumer-group bug regression: both clients must see the event."""
    client = StreamClient()
    task_id = "00000000-0000-0000-0000-00000000ef01"
    a = client.subscribe_task_events(task_id)
    b = client.subscribe_task_events(task_id)
    time.sleep(0.05)
    a.get_message(ignore_subscribe_messages=True, timeout=0.1)
    b.get_message(ignore_subscribe_messages=True, timeout=0.1)

    try:
        client.publish_task_event("task.test.multi", {"task_id": task_id})
        seen_a = seen_b = False
        deadline = time.time() + 2.0
        while time.time() < deadline and not (seen_a and seen_b):
            if not seen_a:
                m = a.get_message(ignore_subscribe_messages=True, timeout=0.2)
                if m and m.get("type") == "message":
                    seen_a = True
            if not seen_b:
                m = b.get_message(ignore_subscribe_messages=True, timeout=0.2)
                if m and m.get("type") == "message":
                    seen_b = True
        assert seen_a and seen_b
    finally:
        a.unsubscribe()
        a.close()
        b.unsubscribe()
        b.close()
