"""Unified HARNESS_WORKDIR resolution for all runners."""

from __future__ import annotations

from pathlib import Path

from agent_runtime.harness.runners._cli_common import resolve_harness_workdir
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
        tmp_path / "default-ws",
    )
    got = resolve_harness_workdir(None)
    assert got == str((tmp_path / "default-ws").resolve())
    assert Path(got).is_dir()


def test_runners_share_harness_workdir(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_WORKDIR", str(tmp_path / "ws"))
    monkeypatch.delenv("CLAUDE_WORKDIR", raising=False)
    monkeypatch.delenv("DSH_WORKSPACE", raising=False)
    monkeypatch.delenv("PI_WORKDIR", raising=False)
    expected = str((tmp_path / "ws").resolve())
    assert ClaudeCliRunner(binary="claude").cwd == expected
    assert DeepSeekHarnessRunner(binary="dsh").workspace == expected
    assert PiCliRunner(binary="pi").cwd == expected
