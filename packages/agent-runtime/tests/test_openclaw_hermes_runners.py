"""Unit tests for OpenClaw / Hermes runner helpers and factory wiring."""

from __future__ import annotations

from agent_runtime.harness.runners import create_runner
from agent_runtime.harness.runners.hermes import HermesCliRunner
from agent_runtime.harness.runners.openclaw import OpenClawCliRunner, _extract_final_text


def test_create_runner_openclaw_and_hermes():
    assert isinstance(create_runner("openclaw"), OpenClawCliRunner)
    assert isinstance(create_runner("openclaw_cli"), OpenClawCliRunner)
    assert isinstance(create_runner("hermes"), HermesCliRunner)
    assert isinstance(create_runner("hermes_agent"), HermesCliRunner)


def test_openclaw_extract_final_from_json_envelope():
    raw = '{"ok": true, "status": "ok", "final": "OPENCLAW_HEADLESS_OK", "payloads": [{"text": "alt"}]}'
    assert _extract_final_text(raw) == "OPENCLAW_HEADLESS_OK"


def test_openclaw_extract_final_from_payloads():
    raw = '{"ok": true, "payloads": [{"text": "hello from payload"}]}'
    assert _extract_final_text(raw) == "hello from payload"


def test_openclaw_extract_falls_back_to_plain_text():
    assert _extract_final_text("just plain output") == "just plain output"


def test_readiness_reports_missing_binary(monkeypatch):
    monkeypatch.setattr(
        "agent_runtime.harness.runners.openclaw.resolve_binary", lambda _n: None
    )
    monkeypatch.setattr(
        "agent_runtime.harness.runners.hermes.resolve_binary", lambda _n: None
    )
    assert OpenClawCliRunner().readiness()["ready"] is False
    assert HermesCliRunner().readiness()["ready"] is False
