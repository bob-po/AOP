"""AgentCollaborator heartbeat helpers."""

from __future__ import annotations

import sys
import types

from agent_runtime.agent_collab import AgentCollaborator


def test_heartbeat_noop_without_os(monkeypatch):
    monkeypatch.delenv("A2A_OS_URL", raising=False)
    monkeypatch.delenv("GATEWAY_URL", raising=False)
    c = AgentCollaborator(agent_id="claude-code")
    assert c.heartbeat_once() is False
    assert c.start_heartbeat() is False


def test_heartbeat_posts(monkeypatch):
    posts: list[tuple[str, dict]] = []

    class FakeResp:
        status_code = 200

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            posts.append((url, json or {}))
            return FakeResp()

    fake_httpx = types.ModuleType("httpx")
    fake_httpx.Client = FakeClient
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)

    c = AgentCollaborator(agent_id="claude-code", os_url="http://os.test")
    c.set_active_tasks(2)
    assert c.heartbeat_once(version="0.1.0") is True
    assert posts
    assert posts[0][0].endswith("/v1/agent-runtime/claude-code/heartbeat")
    assert posts[0][1]["active_tasks"] == 2
