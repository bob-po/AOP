"""Tests for DeepSeekHarnessRunner fallbacks."""

from __future__ import annotations

import pytest

from agent_runtime.harness.protocol import HarnessEvent, HarnessStatus
from agent_runtime.harness.runners.deepseek import DeepSeekHarnessRunner
from agent_runtime.harness.runners import create_runner


def test_create_runner_aliases():
    assert type(create_runner("pi")).__name__ == "PiCliRunner"
    assert type(create_runner("deepseek")).__name__ == "DeepSeekHarnessRunner"
    assert type(create_runner("claude_cli")).__name__ == "ClaudeCliRunner"


@pytest.mark.asyncio
async def test_deepseek_unavailable_without_key_or_cli(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DSH_HOME", raising=False)
    runner = DeepSeekHarnessRunner(
        binary=str(tmp_path / "no-dsh.exe"),
        prefer="tool_loop",
    )
    events: list[HarnessEvent] = []

    async def on_event(ev: HarnessEvent):
        events.append(ev)

    result = await runner.run(
        task_id="t1",
        message={"parts": [{"type": "text", "text": "hi"}]},
        skill_id="code-assist",
        on_event=on_event,
    )
    assert result.status == HarnessStatus.FAILED
    assert "unavailable" in (result.error or "").lower() or "DEEPSEEK_API_KEY" in (result.error or "")


@pytest.mark.asyncio
async def test_deepseek_tool_loop_with_mock_provider(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")

    class FakeResp:
        content = "from deepseek"
        usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}

    class FakeProvider:
        def __init__(self, cfg):
            self.config = cfg

        def chat_completion(self, request):
            return FakeResp()

    import llm_provider

    monkeypatch.setattr(llm_provider, "OpenAIProvider", FakeProvider)

    runner = DeepSeekHarnessRunner(prefer="tool_loop", binary="__missing_dsh__")
    events: list[HarnessEvent] = []

    async def on_event(ev: HarnessEvent):
        events.append(ev)

    result = await runner.run(
        task_id="t2",
        message={"parts": [{"type": "text", "text": "hello"}], "metadata": {"systemPrompt": "sys"}},
        skill_id="code-assist",
        on_event=on_event,
    )
    assert result.status == HarnessStatus.OK
    assert result.text == "from deepseek"
    assert result.usage.input_tokens == 5
    assert result.usage.output_tokens == 3
    assert result.data.get("mode") == "tool_loop"


def test_deepseek_sets_dsh_home_by_default(tmp_path, monkeypatch):
    from pathlib import Path

    from agent_runtime.harness.runners.deepseek import _ensure_dsh_home

    monkeypatch.delenv("DSH_HOME", raising=False)
    home = _ensure_dsh_home(str(tmp_path / "custom-dsh"))
    assert home == str((tmp_path / "custom-dsh").resolve())
    assert Path(home).is_dir()

    runner = DeepSeekHarnessRunner(
        binary=str(tmp_path / "no-dsh.exe"),
        dsh_home=str(tmp_path / "runner-home"),
    )
    assert "runner-home" in runner.dsh_home
    assert Path(runner.dsh_home).is_dir()
