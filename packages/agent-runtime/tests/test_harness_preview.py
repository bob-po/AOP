"""Live preview flag, TUI argv builders, and tee helper."""

from __future__ import annotations

import subprocess
import sys

from agent_runtime.harness.preview import (
    build_preview_user_prompt,
    claude_tui_argv,
    deepseek_preview_argv,
    extract_codewhale_final_text,
    harness_preview_mode,
    hermes_tui_argv,
    live_preview_enabled,
    openclaw_tui_argv,
    pi_tui_argv,
    preview_binary,
    should_use_live_preview,
)


def test_live_preview_enabled_truthy(monkeypatch):
    for val in ("1", "true", "YES", "on"):
        monkeypatch.setenv("HARNESS_LIVE_PREVIEW", val)
        assert live_preview_enabled() is True


def test_live_preview_enabled_falsy(monkeypatch):
    for val in ("", "0", "false", "off", "no"):
        monkeypatch.setenv("HARNESS_LIVE_PREVIEW", val)
        assert live_preview_enabled() is False
    monkeypatch.delenv("HARNESS_LIVE_PREVIEW", raising=False)
    assert live_preview_enabled() is False


def test_should_use_live_preview_falls_back_without_desktop(monkeypatch):
    monkeypatch.setenv("HARNESS_LIVE_PREVIEW", "1")
    monkeypatch.setattr(
        "agent_runtime.harness.preview.desktop_preview_available",
        lambda: False,
    )
    assert should_use_live_preview() is False


def test_deepseek_preview_argv_tui_default(monkeypatch):
    monkeypatch.delenv("HARNESS_PREVIEW_MODE", raising=False)
    monkeypatch.delenv("CODEWHALE_PREVIEW_MODE", raising=False)
    monkeypatch.delenv("CODEWHALE_PREVIEW_STREAM_JSON", raising=False)
    argv = deepseek_preview_argv("do the thing", binary="codewhale", workspace="C:/ws")
    assert argv[0] == "codewhale"
    assert "exec" not in argv
    assert "--fresh" in argv
    assert "--approval-policy" in argv
    assert "auto" in argv
    assert "-C" in argv
    assert "-p" in argv
    assert argv[argv.index("-p") + 1] == "do the thing"


def test_deepseek_preview_argv_exec_mode(monkeypatch):
    monkeypatch.setenv("CODEWHALE_PREVIEW_MODE", "exec")
    monkeypatch.delenv("HARNESS_PREVIEW_MODE", raising=False)
    monkeypatch.delenv("CODEWHALE_PREVIEW_STREAM_JSON", raising=False)
    argv = deepseek_preview_argv("do the thing", binary="codewhale")
    assert argv[0] == "codewhale"
    assert "exec" in argv
    assert "--auto" in argv
    assert "--output-format" in argv
    assert "text" in argv
    assert "stream-json" not in argv
    assert argv[-1] == "do the thing"


def test_deepseek_preview_argv_stream_json_opt_in(monkeypatch):
    monkeypatch.setenv("HARNESS_PREVIEW_MODE", "exec")
    monkeypatch.setenv("CODEWHALE_PREVIEW_MODE", "exec")
    monkeypatch.setenv("CODEWHALE_PREVIEW_STREAM_JSON", "1")
    argv = deepseek_preview_argv("do the thing", binary="codewhale")
    assert "stream-json" in argv


def test_claude_tui_argv_is_interactive(monkeypatch):
    monkeypatch.delenv("CLAUDE_CLI_PERMISSION_MODE", raising=False)
    monkeypatch.delenv("CLAUDE_CLI_TUI_PERMISSION_MODE", raising=False)
    argv = claude_tui_argv("build it, with commas", binary="claude")
    assert argv[0] == "claude"
    assert "-p" not in argv
    assert "--print" not in argv
    assert "--output-format" not in argv
    assert "--permission-mode" in argv
    assert "--dangerously-skip-permissions" in argv
    # Must be single-token so variadic --allowed-tools cannot swallow the prompt.
    assert any(a.startswith("--allowed-tools=") for a in argv)
    assert "--allowed-tools" not in argv
    assert argv[-2:] == ["--", "build it, with commas"]


def test_pi_tui_argv_is_interactive():
    argv = pi_tui_argv("build it", binary="pi", provider_args=["--provider", "openai"])
    assert argv[0] == "pi"
    assert "--print" not in argv
    assert "--mode" not in argv
    assert "--" in argv
    assert argv[-1] == "build it"


def test_openclaw_tui_argv(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCLAW_PREVIEW_UI", raising=False)
    (tmp_path / "preview_prompt.md").write_text("goal text", encoding="utf-8")
    argv = openclaw_tui_argv("build it", binary="openclaw", workspace=str(tmp_path))
    # Default: isolated agent exec + message-file (tee'd in a new console).
    assert argv[0] == "openclaw"
    assert argv[1:3] == ["agent", "exec"]
    assert "--cwd" in argv
    assert "--message-file" in argv


def test_openclaw_tui_argv_force_chat_ui(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCLAW_PREVIEW_UI", "tui")
    (tmp_path / "preview_prompt.md").write_text("goal", encoding="utf-8")
    argv = openclaw_tui_argv(
        "long prompt",
        binary="openclaw",
        workspace=str(tmp_path),
        session_key="aop-deadbeef",
    )
    assert argv[:3] == ["openclaw", "tui", "--local"]
    assert "--message" in argv
    assert "preview_prompt.md" in argv[argv.index("--message") + 1]
    assert "--session" in argv
    assert argv[argv.index("--session") + 1] == "aop-deadbeef"


def test_hermes_tui_argv(monkeypatch):
    monkeypatch.delenv("HERMES_PREVIEW_UI", raising=False)
    argv = hermes_tui_argv("build it", binary="hermes", model="x")
    assert argv[0] == "hermes"
    assert "-z" in argv
    assert argv[argv.index("-z") + 1] == "build it"
    assert "--yolo" in argv
    assert "chat" not in argv
    assert "--tui" not in argv
    assert "-m" in argv


def test_hermes_tui_argv_force_tui(monkeypatch):
    monkeypatch.setenv("HERMES_PREVIEW_UI", "tui")
    argv = hermes_tui_argv("x" * 5000, binary="hermes")
    assert "--tui" in argv
    assert "-z" in argv
    # Huge prompts become a short seed pointing at workspace files.
    assert "preview_prompt.md" in argv[argv.index("-z") + 1]


def test_looks_like_cli_crash():
    from agent_runtime.harness.preview import looks_like_cli_crash

    assert looks_like_cli_crash("ImportError: cannot import name 'main' from 'cli'")
    assert "not configured" in (looks_like_cli_crash("No inference provider configured") or "")
    assert "auth missing" in (
        looks_like_cli_crash("No route-compatible authentication source") or ""
    )
    assert looks_like_cli_crash("all good answer here") is None


def test_harness_preview_mode_alias(monkeypatch):
    monkeypatch.delenv("HARNESS_PREVIEW_MODE", raising=False)
    monkeypatch.setenv("CODEWHALE_PREVIEW_MODE", "exec")
    assert harness_preview_mode() == "exec"
    monkeypatch.setenv("HARNESS_PREVIEW_MODE", "tui")
    assert harness_preview_mode() == "tui"


def test_preview_binary_uses_env_override(tmp_path, monkeypatch):
    fake = tmp_path / "cw.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("CODEWHALE_CLI_PATH", str(fake))
    monkeypatch.delenv("HARNESS_LIVE_PREVIEW", raising=False)
    got = preview_binary("deepseek-harness")
    assert got == str(fake)


def test_preview_tee_writes_log(tmp_path):
    log = tmp_path / "preview.log"
    cmd = [
        sys.executable,
        "-m",
        "agent_runtime.harness.preview_tee",
        "--log",
        str(log),
        "--",
        sys.executable,
        "-c",
        "import sys; print('hello-preview'); print('err', file=sys.stderr)",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0
    body = log.read_text(encoding="utf-8", errors="replace")
    assert "hello-preview" in body
    assert "err" in body


def test_build_preview_user_prompt_leads_with_goal():
    prompt = build_preview_user_prompt(
        "调研ui2v并输出研究摘要",
        system="# DeepSeek Harness Agent\nYou are a harness.",
        skill_id="deepseek-harness",
    )
    assert prompt.index("调研ui2v") < prompt.index("DeepSeek Harness Agent")
    assert "User goal" in prompt
    assert "empty" in prompt.lower()


def test_extract_codewhale_final_text_from_metadata():
    stream = "\n".join(
        [
            '{"type":"tool_use","name":"bash"}',
            "Workspace is empty — ignore me intermediate",
            (
                '{"type":"metadata","meta":{"visible_final_answer_excerpt":'
                '"## ui2v 研究摘要\\n\\n产品定位：...","status":"completed"},'
                '"schema":"codewhale.exec-stream"}'
            ),
            '{"type":"done","schema":"codewhale.exec-stream"}',
        ]
    )
    got = extract_codewhale_final_text(stream)
    assert "ui2v 研究摘要" in got
    assert "tool_use" not in got


def test_extract_codewhale_final_text_from_prose_fallback():
    stream = "\n".join(
        [
            '{"type":"tool_use","name":"bash"}',
            '{"type":"tool_result","output":"ok"}',
            "Here is a sufficiently long research summary about ui2v for testing.",
            "It covers product, market, and open sources.",
            '{"type":"done"}',
        ]
    )
    got = extract_codewhale_final_text(stream)
    assert "research summary about ui2v" in got
    assert "tool_use" not in got
