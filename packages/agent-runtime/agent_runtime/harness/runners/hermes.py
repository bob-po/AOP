"""Hermes Agent CLI harness runner (``hermes -z`` oneshot).

See https://hermes-agent.nousresearch.com/docs/user-guide/cli

Prefer top-level ``-z`` over ``hermes chat``: on many Windows installs ``chat``
imports a shadowed site-packages ``cli`` and crashes with ImportError.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from ..cost import estimate_cost
from ..process import ProcessSupervisor
from ..protocol import (
    EventCallback,
    HarnessEventType,
    HarnessResult,
    HarnessStatus,
    TokenUsage,
)
from ._cli_common import (
    bump_stream_limit,
    compose_cli_prompt,
    emit_event,
    message_text,
    readline_unlimited,
    resolve_binary,
    resolve_harness_workdir,
    skill_label,
    system_prompt_from_message,
    workdir_from_message,
)
from ..preview import (
    build_preview_user_prompt,
    collect_preview_artifacts,
    harness_preview_mode,
    hermes_tui_argv,
    looks_like_cli_crash,
    prepare_preview_workspace,
    run_preview_and_collect,
    should_use_live_preview,
)

logger = logging.getLogger(__name__)


class HermesCliRunner:
    """Invoke Hermes Agent CLI in non-interactive chat mode."""

    def __init__(
        self,
        *,
        binary: Optional[str] = None,
        timeout_s: float = 1800.0,
        extra_args: Optional[list[str]] = None,
        cwd: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        supervisor: Optional[ProcessSupervisor] = None,
    ):
        self.binary = binary or os.getenv("HERMES_CLI_PATH") or "hermes"
        self.timeout_s = float(os.getenv("HERMES_CLI_TIMEOUT_S") or timeout_s)
        self.extra_args = list(extra_args or [])
        self.base_workdir = resolve_harness_workdir(cwd, legacy_env=("HERMES_WORKDIR",))
        self.env = env
        self.supervisor = supervisor or ProcessSupervisor()

    @property
    def cwd(self) -> str:
        """Parent workdir root (per-run cwd is nested under task × agent)."""
        return self.base_workdir

    def resolve_binary(self) -> Optional[str]:
        return resolve_binary(self.binary)

    def readiness(self) -> dict[str, Any]:
        if self.resolve_binary():
            return {"ready": True, "mode": "cli"}
        return {
            "ready": False,
            "mode": None,
            "reason": (
                f"Hermes CLI not found ({self.binary}). "
                "Install Hermes Agent or set HERMES_CLI_PATH."
            ),
        }

    async def cancel(self, task_id: str) -> bool:
        return await self.supervisor.cancel(task_id)

    async def run(
        self,
        *,
        task_id: str,
        message: dict[str, Any],
        skill_id: str,
        on_event: EventCallback,
    ) -> HarnessResult:
        started = time.monotonic()
        prompt = message_text(message)
        system = system_prompt_from_message(message)
        if system or skill_label(skill_id):
            prompt = compose_cli_prompt(prompt, system=system, skill_id=skill_id)

        binary = self.resolve_binary()
        if not binary:
            err = (
                f"Hermes CLI not found ({self.binary}). "
                "Set HERMES_CLI_PATH or install Hermes Agent."
            )
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "HermesCliRunner", "available": False},
            )

        if not prompt.strip():
            err = "Hermes received an empty user message."
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "HermesCliRunner", "emptyMessage": True},
            )

        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.STATUS,
            payload={"state": "working", "message": "starting hermes chat"},
        )

        msg_file: Optional[Path] = None
        fd, path = tempfile.mkstemp(prefix="aop-hermes-", suffix=".txt", text=True)
        os.close(fd)
        msg_file = Path(path)
        msg_file.write_text(prompt, encoding="utf-8")

        # Top-level oneshot: avoid ``hermes chat`` (ImportError on shadowed ``cli``).
        argv = [binary, "--yolo", "--accept-hooks", "-z", prompt]
        model = (os.getenv("HERMES_MODEL") or "").strip()
        if model:
            argv.extend(["-m", model])
        provider = (os.getenv("HERMES_PROVIDER") or "").strip()
        if provider:
            argv.extend(["--provider", provider])
        toolsets = (os.getenv("HERMES_TOOLSETS") or "").strip()
        if toolsets:
            argv.extend(["-t", toolsets])
        argv.extend(self.extra_args)

        env = dict(self.env or os.environ.copy())
        run_cwd = workdir_from_message(self.base_workdir, task_id=task_id, message=message)
        # Prefer task workspace as Hermes local terminal cwd when unset.
        env.setdefault("MESSAGING_CWD", run_cwd)
        usage = TokenUsage()
        chunks: list[str] = []
        stderr_bits: list[str] = []

        if should_use_live_preview():
            use_tui = harness_preview_mode() == "tui"
            preview_argv = argv
            if use_tui:
                user_goal = message_text(message)
                system = system_prompt_from_message(message)
                preview_prompt = build_preview_user_prompt(
                    user_goal, system=system, skill_id=skill_id
                )
                prepare_preview_workspace(
                    run_cwd, user_goal=user_goal, prompt=preview_prompt
                )
                # Also overwrite query file so a Hermes TUI that picks it up sees the goal.
                try:
                    msg_file.write_text(preview_prompt, encoding="utf-8")
                except OSError:
                    pass
                preview_argv = hermes_tui_argv(
                    preview_prompt,
                    binary=binary,
                    model=model or None,
                    provider=provider or None,
                    toolsets=toolsets or None,
                    extra_args=list(self.extra_args),
                )
                # oneshot/-z → tee; --tui → raw console
                use_tui = "--tui" in preview_argv
            await emit_event(
                on_event,
                task_id=task_id,
                etype=HarnessEventType.STATUS,
                payload={
                    "state": "working",
                    "message": f"live preview: hermes ({'tui' if use_tui else 'oneshot'} console)",
                },
            )

            async def _on_line(line: str) -> None:
                chunks.append(line)
                stripped = line.rstrip("\r\n")
                if stripped:
                    await emit_event(
                        on_event,
                        task_id=task_id,
                        etype=HarnessEventType.DELTA,
                        payload={"text": stripped + "\n"},
                    )

            try:
                rc, raw, killed = await run_preview_and_collect(
                    self.supervisor,
                    task_id,
                    cwd=run_cwd,
                    argv=preview_argv,
                    env=env,
                    timeout_s=self.timeout_s,
                    on_line=None if use_tui else _on_line,
                    interactive=use_tui,
                )
            finally:
                if msg_file is not None:
                    try:
                        msg_file.unlink(missing_ok=True)  # type: ignore[arg-type]
                    except OSError:
                        pass
            usage.wall_time_ms = int((time.monotonic() - started) * 1000)
            text = collect_preview_artifacts(
                run_cwd, fallback=("" if use_tui else ("".join(chunks).strip() or raw.strip()))
            )
            # Don't treat preview.log banner / echoed -z prompt as a real answer.
            out_md = Path(run_cwd) / "output.md"
            if text.lstrip().startswith("[aop-preview]") and not out_md.is_file():
                text = ""
            crash = looks_like_cli_crash(text) or looks_like_cli_crash(raw)
            if killed:
                return HarnessResult(
                    text=text,
                    status=HarnessStatus.TIMEOUT,
                    error=f"timeout after {self.timeout_s}s",
                    skill_id=skill_id,
                    usage=usage,
                    data={"runner": "HermesCliRunner", "livePreview": True},
                )
            if crash or rc not in (0, None) or (use_tui and not text) or not text:
                err = (
                    crash
                    or (f"hermes exited with code {rc}" if rc not in (0, None) else None)
                    or (
                        "hermes TUI exited without writing output.md"
                        if use_tui
                        else "hermes produced no usable output"
                    )
                )
                return HarnessResult(
                    text="",
                    status=HarnessStatus.FAILED,
                    error=err,
                    skill_id=skill_id,
                    usage=usage,
                    data={"runner": "HermesCliRunner", "livePreview": True, "exitCode": rc},
                )
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.FINAL, payload={"state": "completed"}
            )
            return HarnessResult(
                text=text,
                status=HarnessStatus.OK,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "HermesCliRunner", "livePreview": True, "exitCode": rc},
            )

        try:
            mp = await self.supervisor.spawn(task_id, *argv, env=env, cwd=run_cwd)
        except FileNotFoundError:
            err = f"Failed to spawn Hermes CLI: {binary}"
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(text="", status=HarnessStatus.FAILED, error=err, skill_id=skill_id)

        bump_stream_limit(mp.proc.stdout)
        bump_stream_limit(mp.proc.stderr)

        async def _read_stdout() -> None:
            assert mp.proc.stdout is not None
            while True:
                line_b = await readline_unlimited(mp.proc.stdout)
                if not line_b:
                    break
                line = line_b.decode("utf-8", errors="replace")
                chunks.append(line)
                stripped = line.rstrip("\r\n")
                if stripped:
                    await emit_event(
                        on_event,
                        task_id=task_id,
                        etype=HarnessEventType.DELTA,
                        payload={"text": stripped + "\n"},
                    )

        async def _read_stderr() -> None:
            assert mp.proc.stderr is not None
            while True:
                line_b = await readline_unlimited(mp.proc.stderr)
                if not line_b:
                    break
                stderr_bits.append(line_b.decode("utf-8", errors="replace"))

        try:
            await asyncio.wait_for(
                asyncio.gather(_read_stdout(), _read_stderr(), mp.proc.wait()),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            await self.supervisor.cancel(task_id)
            usage.wall_time_ms = int((time.monotonic() - started) * 1000)
            await emit_event(
                on_event,
                task_id=task_id,
                etype=HarnessEventType.ERROR,
                payload={"error": "hermes cli timeout"},
            )
            return HarnessResult(
                text="".join(chunks).strip(),
                status=HarnessStatus.TIMEOUT,
                error=f"timeout after {self.timeout_s}s",
                skill_id=skill_id,
                usage=usage,
                data={"runner": "HermesCliRunner"},
            )
        except Exception as exc:  # noqa: BLE001
            await self.supervisor.cancel(task_id)
            usage.wall_time_ms = int((time.monotonic() - started) * 1000)
            err = f"hermes cli stream error: {exc}"
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="".join(chunks).strip(),
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "HermesCliRunner", "streamError": True},
            )
        finally:
            await self.supervisor.unregister(task_id)
            if msg_file is not None:
                try:
                    msg_file.unlink(missing_ok=True)
                except OSError:
                    pass

        usage.wall_time_ms = int((time.monotonic() - started) * 1000)
        if usage.input_tokens or usage.output_tokens:
            usage.estimated_cost = estimate_cost(
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
            )
        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.USAGE, payload=usage.to_dict()
        )

        text = "".join(chunks).strip()
        rc = mp.returncode
        stderr = "".join(stderr_bits).strip()
        crash = looks_like_cli_crash(text) or looks_like_cli_crash(stderr)
        if crash or rc not in (0, None) or not text:
            if crash:
                err = crash
            elif rc not in (0, None):
                err = stderr or f"hermes exited with code {rc}"
            else:
                err = stderr or "hermes produced no usable output"
            status = HarnessStatus.CANCELED if getattr(mp, "_killed", False) else HarnessStatus.FAILED
            await emit_event(
                on_event,
                task_id=task_id,
                etype=HarnessEventType.ERROR if status == HarnessStatus.FAILED else HarnessEventType.STATUS,
                payload={"error": err} if status == HarnessStatus.FAILED else {"state": "canceled"},
            )
            return HarnessResult(
                text="",
                status=status,
                error=err,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "HermesCliRunner", "exitCode": rc, "stderr": err[:1000]},
            )

        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.FINAL, payload={"state": "completed"}
        )
        return HarnessResult(
            text=text,
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=usage,
            data={
                "runner": "HermesCliRunner",
                "exitCode": rc,
                "stderr": stderr[:500] if stderr else "",
            },
        )
