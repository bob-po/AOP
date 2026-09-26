"""PiCliRunner readiness + tool_loop fallback."""

from __future__ import annotations

import pytest

from agent_runtime.harness.protocol import HarnessEvent, HarnessStatus
from agent_runtime.harness.runners.pi_cli import PiCliRunner
from agent_runtime.harness.runners.deepseek import DeepSeekHarnessRunner


def test_pi_readiness_without_cli_or_key(monkeypatch, tmp_path):
    monkeypatch.delenv("PI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    runner = PiCliRunner(binary=str(tmp_path / "no-pi.exe"))
    ready = runner.readiness()
    assert ready["ready"] is False


def test_deepseek_readiness_without_cli_or_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = DeepSeekHarnessRunner(binary=str(tmp_path / "no-dsh.exe"), prefer="tool_loop")
    ready = runner.readiness()
    assert ready["ready"] is False
    assert "API_KEY" in (ready.get("reason") or "")


def test_deepseek_readiness_with_key(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    runner = DeepSeekHarnessRunner(binary=str(tmp_path / "no-dsh.exe"), prefer="tool_loop")
    ready = runner.readiness()
    assert ready["ready"] is True


@pytest.mark.asyncio
async def test_pi_tool_loop_with_mock_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PI_MODEL", "gpt-4o-mini")

    class FakeResp:
        content = "from pi tool_loop"
        usage = {"prompt_tokens": 2, "completion_tokens": 4, "total_tokens": 6}

    class FakeProvider:
        def __init__(self, cfg):
            self.config = cfg

        def chat_completion(self, request):
            return FakeResp()

    import llm_provider

    monkeypatch.setattr(llm_provider, "OpenAIProvider", FakeProvider)

    runner = PiCliRunner(binary=str(tmp_path / "missing-pi"))
    assert runner.readiness()["ready"] is True
    events: list[HarnessEvent] = []

    async def on_event(ev: HarnessEvent):
        events.append(ev)

    result = await runner.run(
        task_id="pi-1",
        message={"parts": [{"type": "text", "text": "hi"}], "metadata": {"systemPrompt": "sys"}},
        skill_id="code-assist",
        on_event=on_event,
    )
    assert result.status == HarnessStatus.OK
    assert result.text == "from pi tool_loop"
    assert result.data.get("mode") == "tool_loop"
