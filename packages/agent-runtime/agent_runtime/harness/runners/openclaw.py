"""OpenClaw CLI harness runner (``openclaw agent exec --json``).

See https://docs.openclaw.ai/cli/agent — headless ``agent exec`` owns setup,
cleanup, and a stable JSON envelope (``final`` / ``payloads``).
"""

from __future__ import annotations

import asyncio
import json
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
    emit_event,
    message_text,
    readline_unlimited,
    resolve_binary,
    resolve_harness_workdir,
    system_prompt_from_message,
)

logger = logging.getLogger(__name__)


def _extract_final_text(stdout: str) -> str:
    """Best-effort parse of OpenClaw ``--json`` envelope, else raw stdout."""
    text = (stdout or "").strip()
    if not text:
        return ""
    # Prefer last JSON object on stdout (CLI may print logs then JSON).
    candidates: list[str] = []
    if text.startswith("{"):
        candidates.append(text)
    else:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                candidates.append(line)
                break
        # Multi-line JSON blob at end
        idx = text.rfind("\n{")
        if idx >= 0:
            candidates.append(text[idx + 1 :])
        elif "\n{" not in text and text.rfind("{") > 0:
            candidates.append(text[text.rfind("{") :])
    for raw in candidates:
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        final = obj.get("final")
        if isinstance(final, str) and final.strip():
            return final.strip()
        payloads = obj.get("payloads")
        if isinstance(payloads, list):
            bits: list[str] = []
            for p in payloads:
                if isinstance(p, dict) and isinstance(p.get("text"), str):
                    bits.append(p["text"])
                elif isinstance(p, str):
                    bits.append(p)
            joined = "\n".join(b for b in bits if b.strip()).strip()
            if joined:
                return joined
        for key in ("text", "result", "message", "content"):
            val = obj.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return text


class OpenClawCliRunner:
    """Invoke OpenClaw ``agent exec`` for one embedded headless turn."""

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
        self.binary = binary or os.getenv("OPENCLAW_CLI_PATH") or "openclaw"
        self.timeout_s = float(os.getenv("OPENCLAW_CLI_TIMEOUT_S") or timeout_s)
        self.extra_args = list(extra_args or [])
        self.cwd = resolve_harness_workdir(cwd, legacy_env=("OPENCLAW_WORKDIR",))
        self.env = env
        self.supervisor = supervisor or ProcessSupervisor()

    def resolve_binary(self) -> Optional[str]:
        return resolve_binary(self.binary)

    def readiness(self) -> dict[str, Any]:
        if self.resolve_binary():
            return {"ready": True, "mode": "cli"}
        return {
            "ready": False,
            "mode": None,
            "reason": (
                f"OpenClaw CLI not found ({self.binary}). "
                "Install OpenClaw or set OPENCLAW_CLI_PATH."
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
        if system:
            prompt = f"{system}\n\n---\n\nUser task (skill={skill_id}):\n{prompt}"
        elif prompt:
            prompt = f"User task (skill={skill_id}):\n{prompt}"

        binary = self.resolve_binary()
        if not binary:
            err = (
                f"OpenClaw CLI not found ({self.binary}). "
                "Set OPENCLAW_CLI_PATH or install OpenClaw."
            )
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "OpenClawCliRunner", "available": False},
            )

        if not prompt.strip():
            err = f"OpenClaw received an empty user message (skill={skill_id})."
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "OpenClawCliRunner", "emptyMessage": True},
            )

        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.STATUS,
            payload={"state": "working", "message": "starting openclaw agent exec"},
        )

        msg_file: Optional[Path] = None
        fd, path = tempfile.mkstemp(prefix="aop-openclaw-", suffix=".txt", text=True)
        os.close(fd)
        msg_file = Path(path)
        msg_file.write_text(prompt, encoding="utf-8")

        argv = [
            binary,
            "agent",
            "exec",
            "--cwd",
            self.cwd,
            "--message-file",
            str(msg_file),
            "--json",
        ]
        model = (os.getenv("OPENCLAW_MODEL") or "").strip()
        if model:
            argv.extend(["--model", model])
        timeout_cli = (os.getenv("OPENCLAW_AGENT_TIMEOUT_S") or "").strip()
        if timeout_cli:
            argv.extend(["--timeout", timeout_cli])
        argv.extend(self.extra_args)

        env = dict(self.env or os.environ.copy())
        usage = TokenUsage()
        stdout_bits: list[str] = []
        stderr_bits: list[str] = []

        try:
            mp = await self.supervisor.spawn(task_id, *argv, env=env, cwd=self.cwd)
        except FileNotFoundError:
            err = f"Failed to spawn OpenClaw CLI: {binary}"
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(text="", status=HarnessStatus.FAILED, error=err, skill_id=skill_id)
        finally:
            pass

        bump_stream_limit(mp.proc.stdout)
        bump_stream_limit(mp.proc.stderr)

        async def _read_stdout() -> None:
            assert mp.proc.stdout is not None
            while True:
                line_b = await readline_unlimited(mp.proc.stdout)
                if not line_b:
                    break
                chunk = line_b.decode("utf-8", errors="replace")
                stdout_bits.append(chunk)
                # Stream progressive plain lines as deltas when not JSON-only.
                line = chunk.rstrip("\r\n")
                if line and not line.lstrip().startswith("{"):
                    await emit_event(
                        on_event,
                        task_id=task_id,
                        etype=HarnessEventType.DELTA,
                        payload={"text": line + "\n"},
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
                payload={"error": "openclaw cli timeout"},
            )
            return HarnessResult(
                text=_extract_final_text("".join(stdout_bits)),
                status=HarnessStatus.TIMEOUT,
                error=f"timeout after {self.timeout_s}s",
                skill_id=skill_id,
                usage=usage,
                data={"runner": "OpenClawCliRunner"},
            )
        except Exception as exc:  # noqa: BLE001
            await self.supervisor.cancel(task_id)
            usage.wall_time_ms = int((time.monotonic() - started) * 1000)
            err = f"openclaw cli stream error: {exc}"
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text=_extract_final_text("".join(stdout_bits)),
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "OpenClawCliRunner", "streamError": True},
            )
        finally:
            await self.supervisor.unregister(task_id)
            if msg_file is not None:
                try:
                    msg_file.unlink(missing_ok=True)
                except OSError:
                    pass

        usage.wall_time_ms = int((time.monotonic() - started) * 1000)
        text = _extract_final_text("".join(stdout_bits))
        if text:
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.DELTA, payload={"text": text}
            )
        if usage.input_tokens or usage.output_tokens:
            usage.estimated_cost = estimate_cost(
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
            )
        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.USAGE, payload=usage.to_dict()
        )

        rc = mp.returncode
        if rc not in (0, None) and not text:
            err = "".join(stderr_bits).strip() or f"openclaw exited with code {rc}"
            status = HarnessStatus.CANCELED if getattr(mp, "_killed", False) else HarnessStatus.FAILED
            await emit_event(
                on_event,
                task_id=task_id,
                etype=HarnessEventType.ERROR if status == HarnessStatus.FAILED else HarnessEventType.STATUS,
                payload={"error": err} if status == HarnessStatus.FAILED else {"state": "canceled"},
            )
            return HarnessResult(
                text=text,
                status=status,
                error=err,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "OpenClawCliRunner", "exitCode": rc, "stderr": err[:1000]},
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
                "runner": "OpenClawCliRunner",
                "exitCode": rc,
                "stderr": "".join(stderr_bits)[:500] if stderr_bits else "",
            },
        )
