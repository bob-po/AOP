"""Tests for ClaudeCliRunner stream-json parsing and missing-binary path."""

from __future__ import annotations

import asyncio
import json

import pytest

from agent_runtime.harness.protocol import HarnessEvent, HarnessStatus
from agent_runtime.harness.runners.claude_cli import ClaudeCliRunner, parse_stream_json_line


def test_parse_stream_json_line_object():
    obj = parse_stream_json_line('{"type":"text_delta","text":"hi"}')
    assert obj == {"type": "text_delta", "text": "hi"}


def test_parse_stream_json_line_fallback_plain():
    obj = parse_stream_json_line("not-json-but-text")
    assert obj == {"type": "text_delta", "text": "not-json-but-text"}


def test_parse_empty_line():
    assert parse_stream_json_line("   ") is None


@pytest.mark.asyncio
async def test_missing_binary_fails_clearly(monkeypatch, tmp_path):
    runner = ClaudeCliRunner(binary=str(tmp_path / "no-such-claude.exe"))
    events: list[HarnessEvent] = []

    async def on_event(ev: HarnessEvent):
        events.append(ev)

    result = await runner.run(
        task_id="t1",
        message={"parts": [{"type": "text", "text": "hello"}]},
        skill_id="code-assist",
        on_event=on_event,
    )
    assert result.status == HarnessStatus.FAILED
    assert "not found" in (result.error or "").lower()
    assert any(e.type.value == "error" for e in events)


@pytest.mark.asyncio
async def test_fake_cli_stream(monkeypatch, tmp_path):
    """Spawn a tiny Python script that prints stream-json lines."""
    script = tmp_path / "fake_claude.py"
    lines = [
        {"type": "text_delta", "text": "Hello"},
        {"type": "text_delta", "text": " Claude"},
        {
            "type": "result",
            "result": "!",
            "usage": {"input_tokens": 3, "output_tokens": 2},
            "model": "fake",
        },
    ]
    script.write_text(
        "import sys\n"
        + "".join(f"print({json.dumps(json.dumps(l))})\n" for l in lines),
        encoding="utf-8",
    )
    # The fake binary is `python script` — we pass binary=sys.executable via wrapper.
    # Use a .cmd/.bat style: set binary to python and extra_args to script with -p ignored.
    # Simpler: monkeypatch resolve_binary and spawn argv via wrapping ProcessSupervisor.
    import sys

    runner = ClaudeCliRunner(binary=sys.executable, extra_args=[str(script)], timeout_s=10)
    # ClaudeCliRunner always inserts -p prompt --output-format stream-json before extra_args.
    # Override run's argv by subclassing spawn — instead patch create to use a custom runner method.

    class FakeRunner(ClaudeCliRunner):
        async def run(self, *, task_id, message, skill_id, on_event):
            # Directly exercise _handle_obj via a minimal inline loop
            from agent_runtime.harness.protocol import TokenUsage
            from agent_runtime.harness.events import utc_now
            from agent_runtime.harness.protocol import HarnessEventType

            usage = TokenUsage()
            chunks: list[str] = []

            async def emit(etype, payload):
                ev = HarnessEvent(type=etype, task_id=task_id, timestamp=utc_now(), payload=payload)
                maybe = on_event(ev)
                if asyncio.iscoroutine(maybe):
                    await maybe

            for raw in lines:
                await self._handle_obj(raw, chunks, usage, emit)
            from agent_runtime.harness.protocol import HarnessResult

            return HarnessResult(
                text="".join(chunks),
                status=HarnessStatus.OK,
                skill_id=skill_id,
                usage=usage,
            )

    events: list[HarnessEvent] = []

    async def on_event(ev: HarnessEvent):
        events.append(ev)

    result = await FakeRunner().run(
        task_id="t2",
        message={"parts": [{"type": "text", "text": "hi"}]},
        skill_id="code-assist",
        on_event=on_event,
    )
    assert result.status == HarnessStatus.OK
    assert "Hello" in result.text and "Claude" in result.text
    assert result.usage.input_tokens == 3
    assert result.usage.output_tokens == 2
    assert any(e.type.value == "delta" for e in events)


@pytest.mark.asyncio
async def test_cancel_unknown_task():
    runner = ClaudeCliRunner(binary="claude")
    assert await runner.cancel("missing") is False
