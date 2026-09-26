"""Pi coding-agent CLI harness runner (``pi --mode json``).

See https://github.com/earendil-works/pi — JSON event stream mode emits
JSONL session events (message_update text_delta, usage, agent_settled).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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
    openai_compatible_api_key,
    readline_unlimited,
    resolve_binary,
    run_openai_compatible_sync,
    system_prompt_from_message,
)

logger = logging.getLogger(__name__)


def _pi_api_key() -> str:
    return openai_compatible_api_key("PI_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")


def _pi_base_url() -> str:
    if (os.getenv("PI_BASE_URL") or "").strip():
        return os.getenv("PI_BASE_URL") or ""
    if (os.getenv("OPENAI_BASE_URL") or "").strip():
        return os.getenv("OPENAI_BASE_URL") or ""
    if (os.getenv("DEEPSEEK_BASE_URL") or "").strip():
        return os.getenv("DEEPSEEK_BASE_URL") or ""
    if (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        return "https://api.deepseek.com"
    return "https://api.openai.com/v1"


def _pi_model() -> str:
    return (
        os.getenv("PI_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or os.getenv("OPENAI_MODEL")
        or "deepseek-chat"
    )


def _pi_cli_provider_args() -> list[str]:
    """Pick provider/model flags from env so headless runs skip interactive /login."""
    explicit_provider = (os.getenv("PI_PROVIDER") or "").strip()
    explicit_model = (os.getenv("PI_MODEL") or "").strip()
    args: list[str] = []
    if explicit_provider:
        args.extend(["--provider", explicit_provider])
    if explicit_model:
        # Supports "provider/id" form
        args.extend(["--model", explicit_model])
        return args

    if (os.getenv("DEEPSEEK_API_KEY") or "").strip():
        if not explicit_provider:
            args.extend(["--provider", "deepseek"])
        args.extend(["--model", os.getenv("DEEPSEEK_MODEL") or "deepseek-flash"])
        return args
    if (os.getenv("OPENAI_API_KEY") or "").strip():
        if not explicit_provider:
            args.extend(["--provider", "openai"])
        args.extend(["--model", os.getenv("OPENAI_MODEL") or "gpt-4o-mini"])
        return args
    if (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        if not explicit_provider:
            args.extend(["--provider", "anthropic"])
        args.extend(["--model", os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5"])
        return args
    if explicit_provider:
        return args
    return []


def _looks_like_login_prompt(text: str) -> bool:
    low = (text or "").lower()
    return "/login" in low or "log into a provider" in low or "use /login" in low


def parse_pi_jsonl_line(line: str) -> dict[str, Any] | None:
    line = (line or "").rstrip("\r\n")
    if not line.strip():
        return None
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return {"type": "text_delta", "text": line}
    return obj if isinstance(obj, dict) else {"type": "text_delta", "text": str(obj)}


def _usage_from_pi(usage: dict[str, Any] | None, model: Optional[str] = None) -> Optional[TokenUsage]:
    if not isinstance(usage, dict):
        return None
    inp = int(usage.get("input") or usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
    out = int(usage.get("output") or usage.get("output_tokens") or usage.get("completion_tokens") or 0)
    cost = usage.get("cost") or {}
    est = 0.0
    if isinstance(cost, dict):
        est = float(cost.get("total") or 0.0)
    if not inp and not out and est <= 0:
        return None
    if est <= 0:
        est = estimate_cost(input_tokens=inp, output_tokens=out)
    return TokenUsage(input_tokens=inp, output_tokens=out, model=model, estimated_cost=est)


class PiCliRunner:
    """Invoke Pi agent harness: ``pi --mode json --no-session <prompt>``."""

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
        self.binary = binary or os.getenv("PI_CLI_PATH") or "pi"
        self.timeout_s = float(os.getenv("PI_CLI_TIMEOUT_S") or timeout_s)
        self.extra_args = list(extra_args or [])
        self.cwd = cwd or os.getenv("PI_WORKDIR") or None
        self.env = env
        self.supervisor = supervisor or ProcessSupervisor()

    def resolve_binary(self) -> Optional[str]:
        return resolve_binary(self.binary)

    def readiness(self) -> dict[str, Any]:
        has_key = bool(_pi_api_key() or (os.getenv("ANTHROPIC_API_KEY") or "").strip())
        if self.resolve_binary() and has_key:
            return {"ready": True, "mode": "cli"}
        if has_key:
            return {"ready": True, "mode": "tool_loop"}
        if self.resolve_binary():
            return {
                "ready": False,
                "mode": None,
                "reason": (
                    "Pi CLI found but no provider API key. Set DEEPSEEK_API_KEY "
                    "(or OPENAI_API_KEY / ANTHROPIC_API_KEY) in agents/harness-agent/.env."
                ),
            }
        return {
            "ready": False,
            "mode": None,
            "reason": (
                "Pi CLI not found (pi). Install @earendil-works/pi-coding-agent "
                "or set PI_CLI_PATH / DEEPSEEK_API_KEY for tool_loop fallback."
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
        binary = self.resolve_binary()
        if not binary:
            return await self._run_tool_loop(
                task_id=task_id, message=message, skill_id=skill_id, on_event=on_event
            )
        return await self._run_cli(
            task_id=task_id,
            message=message,
            skill_id=skill_id,
            on_event=on_event,
            binary=binary,
        )

    async def _run_tool_loop(
        self,
        *,
        task_id: str,
        message: dict[str, Any],
        skill_id: str,
        on_event: EventCallback,
    ) -> HarnessResult:
        started = time.monotonic()
        prompt = message_text(message)
        system = system_prompt_from_message(message) or (
            "You are Pi, a helpful coding agent."
        )
        api_key = _pi_api_key()
        if not api_key:
            err = (
                "Pi CLI not found (pi). Install @earendil-works/pi-coding-agent "
                "or set PI_CLI_PATH / PI_API_KEY (or OPENAI_API_KEY) for tool_loop fallback."
            )
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "PiCliRunner", "mode": "tool_loop", "available": False},
            )

        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.STATUS,
            payload={"state": "working", "message": "pi tool_loop"},
        )
        try:
            text, usage = await asyncio.to_thread(
                run_openai_compatible_sync,
                prompt=prompt,
                system=system,
                skill_id=skill_id,
                api_key=api_key,
                base_url=_pi_base_url(),
                model=_pi_model(),
            )
        except Exception as exc:  # noqa: BLE001
            err = f"Pi tool_loop failed: {exc}"
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "PiCliRunner", "mode": "tool_loop"},
            )

        usage.wall_time_ms = int((time.monotonic() - started) * 1000)
        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.USAGE, payload=usage.to_dict()
        )
        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.DELTA,
            payload={"text": text},
        )
        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.FINAL, payload={"state": "completed"}
        )
        return HarnessResult(
            text=text,
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=usage,
            data={"runner": "PiCliRunner", "mode": "tool_loop"},
        )

    async def _run_cli(
        self,
        *,
        task_id: str,
        message: dict[str, Any],
        skill_id: str,
        on_event: EventCallback,
        binary: str,
    ) -> HarnessResult:
        started = time.monotonic()
        prompt = message_text(message)
        system = system_prompt_from_message(message)
        if not prompt:
            err = (
                "Pi CLI received an empty user message "
                f"(skill={skill_id}). Check A2A message.parts text."
            )
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "PiCliRunner", "emptyMessage": True},
            )

        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.STATUS,
            payload={"state": "working", "message": "starting pi cli"},
        )

        # Keep the user goal as the primary CLI message. System prompt is separate.
        # On Windows, multiline --system-prompt argv breaks CreateProcess quoting —
        # write to a temp file and use --append-system-prompt (accepts file path).
        argv = [binary, "--mode", "json", "--print", "--no-session"]
        argv.extend(_pi_cli_provider_args())
        if os.getenv("PI_OFFLINE", "").lower() in {"1", "true", "yes"}:
            argv.append("--offline")
        sys_file: Optional[Path] = None
        if system:
            import tempfile

            fd, path = tempfile.mkstemp(prefix="aop-pi-sys-", suffix=".md", text=True)
            os.close(fd)
            sys_file = Path(path)
            sys_file.write_text(system, encoding="utf-8")
            argv.extend(
                [
                    "--system-prompt",
                    f"You are Pi Agent (skill={skill_id}). Follow the user goal carefully.",
                ]
            )
            argv.extend(["--append-system-prompt", str(sys_file)])
        argv.extend(self.extra_args)
        argv.extend(["--", prompt])

        env = dict(self.env or os.environ.copy())
        usage = TokenUsage()
        chunks: list[str] = []
        stderr_bits: list[str] = []
        model: Optional[str] = None

        try:
            mp = await self.supervisor.spawn(task_id, *argv, env=env, cwd=self.cwd)
        except FileNotFoundError:
            err = f"Failed to spawn Pi CLI: {binary}"
            await emit_event(on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err})
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
                line = line_b.decode("utf-8", errors="replace")
                obj = parse_pi_jsonl_line(line)
                if not obj:
                    continue
                await self._handle_obj(obj, chunks, usage, on_event, task_id)

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
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": "pi cli timeout"}
            )
            return HarnessResult(
                text="".join(chunks),
                status=HarnessStatus.TIMEOUT,
                error=f"timeout after {self.timeout_s}s",
                skill_id=skill_id,
                usage=usage,
                data={"runner": "PiCliRunner"},
            )
        except Exception as exc:  # noqa: BLE001
            await self.supervisor.cancel(task_id)
            usage.wall_time_ms = int((time.monotonic() - started) * 1000)
            err = f"pi cli stream error: {exc}"
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="".join(chunks),
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "PiCliRunner", "streamError": True},
            )
        finally:
            await self.supervisor.unregister(task_id)
            if sys_file is not None:
                try:
                    sys_file.unlink(missing_ok=True)
                except OSError:
                    pass

        usage.wall_time_ms = int((time.monotonic() - started) * 1000)
        if usage.model is None and model:
            usage.model = model
        if usage.estimated_cost <= 0 and (usage.input_tokens or usage.output_tokens):
            usage.estimated_cost = estimate_cost(
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
            )
        await emit_event(on_event, task_id=task_id, etype=HarnessEventType.USAGE, payload=usage.to_dict())

        rc = mp.returncode
        text = "".join(chunks).strip()
        if not text:
            # Fallback: last message_end may have put content only in structured form
            text = text or "".join(stderr_bits[-3:]).strip()

        combined = "\n".join([text, "".join(stderr_bits)]).strip()
        if _looks_like_login_prompt(combined):
            logger.info("pi cli asked for /login; falling back to tool_loop")
            return await self._run_tool_loop(
                task_id=task_id, message=message, skill_id=skill_id, on_event=on_event
            )

        if rc not in (0, None) and not text:
            err = "".join(stderr_bits).strip() or f"pi exited with code {rc}"
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
                data={"runner": "PiCliRunner", "exitCode": rc},
            )

        if not text:
            err = (
                "".join(stderr_bits).strip()
                or "Pi CLI returned empty output (no assistant text)"
            )
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "PiCliRunner", "exitCode": rc, "emptyOutput": True},
            )

        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.FINAL, payload={"state": "completed"}
        )
        return HarnessResult(
            text=text,
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=usage,
            data={"runner": "PiCliRunner", "exitCode": rc},
        )

    async def _handle_obj(
        self,
        obj: dict[str, Any],
        chunks: list[str],
        usage: TokenUsage,
        on_event: EventCallback,
        task_id: str,
    ) -> None:
        otype = str(obj.get("type") or "")

        if otype == "message_update":
            u = _usage_from_pi(obj.get("usage") if isinstance(obj.get("usage"), dict) else None)
            if u:
                usage.input_tokens = max(usage.input_tokens, u.input_tokens)
                usage.output_tokens = max(usage.output_tokens, u.output_tokens)
                if u.estimated_cost:
                    usage.estimated_cost = u.estimated_cost
            ame = obj.get("assistantMessageEvent") or {}
            if isinstance(ame, dict):
                et = str(ame.get("type") or "")
                if et == "text_delta":
                    delta = str(ame.get("delta") or "")
                    if delta:
                        chunks.append(delta)
                        await emit_event(
                            on_event,
                            task_id=task_id,
                            etype=HarnessEventType.DELTA,
                            payload={"text": delta},
                        )
                elif et == "text_end":
                    content = str(ame.get("content") or "")
                    if content and content not in "".join(chunks):
                        if not chunks:
                            chunks.append(content)
                            await emit_event(
                                on_event,
                                task_id=task_id,
                                etype=HarnessEventType.DELTA,
                                payload={"text": content},
                            )
            return

        if otype == "message_end":
            msg = obj.get("message") or {}
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                content = msg.get("content")
                text = ""
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text += str(block.get("text") or block.get("content") or "")
                        elif isinstance(block, str):
                            text += block
                if text and text not in "".join(chunks):
                    # Prefer authoritative final message over deltas
                    if not chunks:
                        chunks.append(text)
                        await emit_event(
                            on_event,
                            task_id=task_id,
                            etype=HarnessEventType.DELTA,
                            payload={"text": text},
                        )
                    elif "".join(chunks) != text:
                        chunks.clear()
                        chunks.append(text)
            return

        if otype == "tool_execution_start":
            await emit_event(
                on_event,
                task_id=task_id,
                etype=HarnessEventType.TOOL,
                payload={
                    "toolName": obj.get("toolName"),
                    "toolCallId": obj.get("toolCallId"),
                    "args": obj.get("args"),
                },
            )
            return

        if otype in {"error", "extension_error"}:
            await emit_event(
                on_event,
                task_id=task_id,
                etype=HarnessEventType.ERROR,
                payload={"error": str(obj.get("error") or obj)},
            )


__all__ = ["PiCliRunner", "parse_pi_jsonl_line"]
