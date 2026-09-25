"""Tests for PiCliRunner JSONL parsing and missing-binary path."""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.harness.protocol import HarnessEvent, HarnessStatus
from agent_runtime.harness.runners.pi_cli import PiCliRunner, parse_pi_jsonl_line


def test_parse_pi_session_and_delta():
    assert parse_pi_jsonl_line('{"type":"session","id":"x"}')["type"] == "session"
    obj = parse_pi_jsonl_line(
        '{"type":"message_update","usage":{"input":1,"output":2},"assistantMessageEvent":{"type":"text_delta","delta":"Hi"}}'
    )
    assert obj["assistantMessageEvent"]["delta"] == "Hi"


def test_parse_pi_plain_fallback():
    assert parse_pi_jsonl_line("not-json") == {"type": "text_delta", "text": "not-json"}


@pytest.mark.asyncio
async def test_pi_missing_binary(tmp_path):
    runner = PiCliRunner(binary=str(tmp_path / "no-pi.exe"))
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


@pytest.mark.asyncio
async def test_pi_handle_message_update_deltas():
    runner = PiCliRunner(binary="pi")
    chunks: list[str] = []
    from agent_runtime.harness.protocol import TokenUsage

    usage = TokenUsage()
    events: list[HarnessEvent] = []

    async def on_event(ev: HarnessEvent):
        events.append(ev)

    await runner._handle_obj(
        {
            "type": "message_update",
            "usage": {"input": 10, "output": 4, "cost": {"total": 0.01}},
            "assistantMessageEvent": {"type": "text_delta", "delta": "Hello"},
        },
        chunks,
        usage,
        on_event,
        "t2",
    )
    await runner._handle_obj(
        {
            "type": "message_end",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Hello world"}]},
        },
        chunks,
        usage,
        on_event,
        "t2",
    )
    assert "Hello" in "".join(chunks)
    assert usage.input_tokens == 10
    assert usage.output_tokens == 4
    assert any(e.type.value == "delta" for e in events)
