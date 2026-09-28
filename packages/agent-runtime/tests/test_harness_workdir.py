"""Unified HARNESS_WORKDIR resolution + per task × agent nesting."""

from __future__ import annotations

from pathlib import Path

from agent_runtime.harness.runners._cli_common import (
    resolve_harness_workdir,
    resolve_run_workdir,
    workdir_from_message,
)
from agent_runtime.harness.runners.claude_cli import ClaudeCliRunner
from agent_runtime.harness.runners.deepseek import DeepSeekHarnessRunner
from agent_runtime.harness.runners.pi_cli import PiCliRunner


def test_resolve_explicit_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_WORKDIR", str(tmp_path / "shared"))
    monkeypatch.setenv("DSH_WORKSPACE", str(tmp_path / "legacy"))
    got = resolve_harness_workdir(str(tmp_path / "explicit"))
    assert got == str((tmp_path / "explicit").resolve())
    assert Path(got).is_dir()


def test_resolve_harness_workdir_over_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_WORKDIR", str(tmp_path / "shared"))
    monkeypatch.setenv("PI_WORKDIR", str(tmp_path / "legacy-pi"))
    got = resolve_harness_workdir(None, legacy_env=("PI_WORKDIR",))
    assert got == str((tmp_path / "shared").resolve())


def test_resolve_legacy_when_shared_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("HARNESS_WORKDIR", raising=False)
    monkeypatch.setenv("CLAUDE_WORKDIR", str(tmp_path / "claude-only"))
    got = resolve_harness_workdir(None, legacy_env=("CLAUDE_WORKDIR",))
    assert got == str((tmp_path / "claude-only").resolve())


def test_resolve_default_sandbox(monkeypatch, tmp_path):
    monkeypatch.delenv("HARNESS_WORKDIR", raising=False)
    monkeypatch.delenv("CLAUDE_WORKDIR", raising=False)
    monkeypatch.delenv("DSH_WORKSPACE", raising=False)
    monkeypatch.delenv("PI_WORKDIR", raising=False)
    # Point home at tmp so we do not touch the real ~/.aop
    monkeypatch.setattr(
        "agent_runtime.harness.runners._cli_common._DEFAULT_WORKDIR",
        tmp_path / "workspaces",
    )
    got = resolve_harness_workdir(None)
    assert got == str((tmp_path / "workspaces").resolve())
    assert Path(got).is_dir()


def test_runners_share_parent_workdir_root(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_WORKDIR", str(tmp_path / "ws"))
    monkeypatch.delenv("CLAUDE_WORKDIR", raising=False)
    monkeypatch.delenv("DSH_WORKSPACE", raising=False)
    monkeypatch.delenv("PI_WORKDIR", raising=False)
    expected = str((tmp_path / "ws").resolve())
    assert ClaudeCliRunner(binary="claude").base_workdir == expected
    assert DeepSeekHarnessRunner(binary="dsh").base_workdir == expected
    assert PiCliRunner(binary="pi").base_workdir == expected
    # Backward-compatible aliases still expose the parent root.
    assert ClaudeCliRunner(binary="claude").cwd == expected
    assert DeepSeekHarnessRunner(binary="dsh").workspace == expected
    assert PiCliRunner(binary="pi").cwd == expected


def test_resolve_run_workdir_nests_task_and_agent(tmp_path):
    base = tmp_path / "ws"
    got = resolve_run_workdir(
        str(base),
        task_id="a2a-child",
        agent_id="claude-code",
        root_task_id="os-task-1",
    )
    assert Path(got) == (base / "os-task-1" / "claude-code").resolve()
    assert Path(got).is_dir()


def test_resolve_run_workdir_falls_back_to_task_id(tmp_path):
    base = tmp_path / "ws"
    got = resolve_run_workdir(str(base), task_id="only-a2a", agent_id="pi")
    assert Path(got) == (base / "only-a2a" / "pi").resolve()


def test_resolve_run_workdir_sanitizes_segments(tmp_path):
    base = tmp_path / "ws"
    got = resolve_run_workdir(
        str(base),
        task_id="x",
        agent_id="../evil/agent",
        root_task_id="task/with\\sep:id",
    )
    path = Path(got)
    assert path.parent.parent == base.resolve()
    assert ".." not in path.parts
    assert path.name == "evil_agent" or path.name.endswith("agent")


def test_workdir_from_message_reads_metadata(tmp_path):
    base = str(tmp_path / "ws")
    got = workdir_from_message(
        base,
        task_id="a2a-1",
        message={
            "metadata": {
                "rootTaskId": "plat-99",
                "agentId": "deepseek-harness",
            }
        },
    )
    assert Path(got) == (tmp_path / "ws" / "plat-99" / "deepseek-harness").resolve()


def test_workdir_from_message_uses_env_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_PROFILE", "openclaw")
    monkeypatch.delenv("AGENT_ID", raising=False)
    got = workdir_from_message(
        str(tmp_path / "ws"),
        task_id="t1",
        message={"metadata": {"correlationId": "corr-1"}},
    )
    assert Path(got) == (tmp_path / "ws" / "corr-1" / "openclaw").resolve()
