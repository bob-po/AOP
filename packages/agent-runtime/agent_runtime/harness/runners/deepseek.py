"""DeepSeek Harness runner.

Integration order (first available wins):

1. Python SDK ``deepseek_harness.DeepSeekHarness``  
   https://github.com/deepseek-ai/deepseek-harness
2. CLI ``dsh --profile headless "<job>"``
3. In-process ``ToolCallingLoop`` + OpenAI-compatible DeepSeek provider
   (``packages/llm-provider``) — zero external harness dependency
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
from ._cli_common import emit_event, message_text, resolve_binary, system_prompt_from_message

logger = logging.getLogger(__name__)


def _deepseek_api_key() -> str:
    return (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )


def _deepseek_base_url() -> str:
    return (
        os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.deepseek.com"
    )


def _deepseek_model() -> str:
    return os.getenv("DSH_MODEL") or os.getenv("DEEPSEEK_MODEL") or "deepseek-chat"


class DeepSeekHarnessRunner:
    """DeepSeek harness with SDK → CLI → tool_loop fallback."""

    def __init__(
        self,
        *,
        binary: Optional[str] = None,
        timeout_s: float = 300.0,
        workspace: Optional[str] = None,
        dsh_home: Optional[str] = None,
        prefer: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        supervisor: Optional[ProcessSupervisor] = None,
    ):
        self.binary = binary or os.getenv("DSH_CLI_PATH") or "dsh"
        self.timeout_s = float(os.getenv("DSH_CLI_TIMEOUT_S") or timeout_s)
        self.workspace = workspace or os.getenv("DSH_WORKSPACE") or os.getcwd()
        self.dsh_home = dsh_home or os.getenv("DSH_HOME") or None
        self.prefer = (prefer or os.getenv("DSH_RUNNER_MODE") or "auto").lower()
        self.env = env
        self.supervisor = supervisor or ProcessSupervisor()
        self._cancel_flags: dict[str, asyncio.Event] = {}

    def resolve_binary(self) -> Optional[str]:
        return resolve_binary(self.binary)

    def sdk_available(self) -> bool:
        try:
            import deepseek_harness  # noqa: F401

            return True
        except ImportError:
            return False

    async def cancel(self, task_id: str) -> bool:
        flag = self._cancel_flags.get(task_id)
        if flag:
            flag.set()
        killed = await self.supervisor.cancel(task_id)
        return bool(flag) or killed

    async def run(
        self,
        *,
        task_id: str,
        message: dict[str, Any],
        skill_id: str,
        on_event: EventCallback,
    ) -> HarnessResult:
        self._cancel_flags[task_id] = asyncio.Event()
        try:
            mode = self.prefer
            if mode == "auto":
                if self.sdk_available() and _deepseek_api_key():
                    mode = "sdk"
                elif self.resolve_binary():
                    mode = "cli"
                else:
                    mode = "tool_loop"

            if mode == "sdk":
                return await self._run_sdk(task_id=task_id, message=message, skill_id=skill_id, on_event=on_event)
            if mode == "cli":
                return await self._run_cli(task_id=task_id, message=message, skill_id=skill_id, on_event=on_event)
            return await self._run_tool_loop(task_id=task_id, message=message, skill_id=skill_id, on_event=on_event)
        finally:
            self._cancel_flags.pop(task_id, None)

    async def _run_sdk(
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
            os.environ.setdefault("DSH_SYSTEM_PROMPT", system)

        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.STATUS,
            payload={"state": "working", "message": "starting deepseek sdk"},
        )

        workspace = Path(self.workspace).resolve()
        dsh_home = Path(self.dsh_home).resolve() if self.dsh_home else Path(tempfile.mkdtemp(prefix="aop-dsh-home-"))
        dsh_home.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)

        def _sync() -> Any:
            from deepseek_harness import DeepSeekHarness

            with DeepSeekHarness(
                provider=os.getenv("DSH_PROVIDER") or "deepseek-official",
                model=_deepseek_model(),
                cwd=str(workspace),
                dsh_home=str(dsh_home),
                profile=os.getenv("DSH_PROFILE") or "sdk-minimal",
            ) as harness:
                return harness.run(prompt, session_id=task_id)

        try:
            result = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=self.timeout_s)
        except asyncio.TimeoutError:
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": "deepseek sdk timeout"}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.TIMEOUT,
                error=f"timeout after {self.timeout_s}s",
                skill_id=skill_id,
                data={"runner": "DeepSeekHarnessRunner", "mode": "sdk"},
            )
        except Exception as exc:  # noqa: BLE001
            # Fall through to CLI / tool_loop
            logger.info("DeepSeek SDK failed (%s); trying fallback", exc)
            if self.resolve_binary():
                return await self._run_cli(task_id=task_id, message=message, skill_id=skill_id, on_event=on_event)
            return await self._run_tool_loop(task_id=task_id, message=message, skill_id=skill_id, on_event=on_event)

        if self._cancel_flags.get(task_id) and self._cancel_flags[task_id].is_set():
            return HarnessResult(
                text="",
                status=HarnessStatus.CANCELED,
                error="canceled",
                skill_id=skill_id,
                data={"runner": "DeepSeekHarnessRunner", "mode": "sdk"},
            )

        text = str(getattr(result, "final_response", None) or getattr(result, "text", None) or result or "")
        usage = TokenUsage(
            model=_deepseek_model(),
            wall_time_ms=int((time.monotonic() - started) * 1000),
        )
        # Best-effort token fields if SDK exposes them
        for attr, field in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens")):
            val = getattr(result, attr, None)
            if val is not None:
                setattr(usage, field, int(val))
        if usage.input_tokens or usage.output_tokens:
            usage.estimated_cost = estimate_cost(
                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
            )

        await emit_event(on_event, task_id=task_id, etype=HarnessEventType.DELTA, payload={"text": text})
        await emit_event(on_event, task_id=task_id, etype=HarnessEventType.USAGE, payload=usage.to_dict())
        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.FINAL, payload={"state": "completed"}
        )
        return HarnessResult(
            text=text,
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=usage,
            data={"runner": "DeepSeekHarnessRunner", "mode": "sdk"},
        )

    async def _run_cli(
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

        binary = self.resolve_binary()
        if not binary:
            return await self._run_tool_loop(task_id=task_id, message=message, skill_id=skill_id, on_event=on_event)

        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.STATUS,
            payload={"state": "working", "message": "starting dsh headless"},
        )

        argv = [binary, "--profile", "headless", prompt]
        env = dict(self.env or os.environ.copy())
        if self.dsh_home:
            env["DSH_HOME"] = self.dsh_home
        if system:
            env["DSH_SYSTEM_PROMPT"] = system

        chunks: list[str] = []
        stderr_bits: list[str] = []
        try:
            mp = await self.supervisor.spawn(task_id, *argv, env=env, cwd=self.workspace)
        except FileNotFoundError:
            return await self._run_tool_loop(task_id=task_id, message=message, skill_id=skill_id, on_event=on_event)

        async def _read_stdout() -> None:
            assert mp.proc.stdout is not None
            while True:
                line_b = await mp.proc.stdout.readline()
                if not line_b:
                    break
                text = line_b.decode("utf-8", errors="replace")
                chunks.append(text)
                await emit_event(
                    on_event, task_id=task_id, etype=HarnessEventType.DELTA, payload={"text": text}
                )

        async def _read_stderr() -> None:
            assert mp.proc.stderr is not None
            while True:
                line_b = await mp.proc.stderr.readline()
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
            return HarnessResult(
                text="".join(chunks),
                status=HarnessStatus.TIMEOUT,
                error=f"timeout after {self.timeout_s}s",
                skill_id=skill_id,
                usage=TokenUsage(wall_time_ms=int((time.monotonic() - started) * 1000)),
                data={"runner": "DeepSeekHarnessRunner", "mode": "cli"},
            )
        finally:
            await self.supervisor.unregister(task_id)

        text = "".join(chunks).strip()
        usage = TokenUsage(
            model=_deepseek_model(),
            wall_time_ms=int((time.monotonic() - started) * 1000),
        )
        rc = mp.returncode
        if rc not in (0, None) and not text:
            err = "".join(stderr_bits).strip() or f"dsh exited with code {rc}"
            # Fall back to tool_loop if headless profile unavailable
            if "profile" in err.lower() or "not found" in err.lower():
                logger.info("dsh headless failed (%s); tool_loop fallback", err[:200])
                return await self._run_tool_loop(
                    task_id=task_id, message=message, skill_id=skill_id, on_event=on_event
                )
            status = HarnessStatus.CANCELED if getattr(mp, "_killed", False) else HarnessStatus.FAILED
            return HarnessResult(
                text=text,
                status=status,
                error=err,
                skill_id=skill_id,
                usage=usage,
                data={"runner": "DeepSeekHarnessRunner", "mode": "cli", "exitCode": rc},
            )

        await emit_event(on_event, task_id=task_id, etype=HarnessEventType.USAGE, payload=usage.to_dict())
        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.FINAL, payload={"state": "completed"}
        )
        return HarnessResult(
            text=text,
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=usage,
            data={"runner": "DeepSeekHarnessRunner", "mode": "cli", "exitCode": rc},
        )

    async def _run_tool_loop(
        self,
        *,
        task_id: str,
        message: dict[str, Any],
        skill_id: str,
        on_event: EventCallback,
    ) -> HarnessResult:
        """Assemble DeepSeek-as-provider + ToolCallingLoop (no tools by default)."""
        started = time.monotonic()
        prompt = message_text(message)
        system = system_prompt_from_message(message) or (
            "You are a helpful software engineer assistant."
        )

        api_key = _deepseek_api_key()
        if not api_key:
            err = (
                "DeepSeek harness unavailable: install deepseek-harness-sdk or dsh CLI, "
                "or set DEEPSEEK_API_KEY for tool_loop fallback."
            )
            await emit_event(on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": err})
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=err,
                skill_id=skill_id,
                data={"runner": "DeepSeekHarnessRunner", "mode": "tool_loop", "available": False},
            )

        await emit_event(
            on_event,
            task_id=task_id,
            etype=HarnessEventType.STATUS,
            payload={"state": "working", "message": "deepseek tool_loop"},
        )

        def _sync() -> tuple[str, TokenUsage]:
            from llm_provider import LLMMessage, LLMProviderConfig, LLMRequest, OpenAIProvider

            cfg = LLMProviderConfig(
                api_key=api_key,
                base_url=_deepseek_base_url(),
                model=_deepseek_model(),
            )
            provider = OpenAIProvider(cfg)
            request = LLMRequest(
                messages=[
                    LLMMessage(role="system", content=f"{system}\n\nActive skill: {skill_id}"),
                    LLMMessage(role="user", content=prompt),
                ],
                model=_deepseek_model(),
            )
            response = provider.chat_completion(request)
            u = response.usage or {}
            usage = TokenUsage(
                input_tokens=int(u.get("prompt_tokens") or 0),
                output_tokens=int(u.get("completion_tokens") or 0),
                model=_deepseek_model(),
            )
            if usage.input_tokens or usage.output_tokens:
                usage.estimated_cost = estimate_cost(
                    input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
                )
            text = str(response.content or "")
            if not text:
                raise RuntimeError("empty DeepSeek response")
            return text, usage

        try:
            text, usage = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=self.timeout_s)
        except Exception as exc:  # noqa: BLE001
            await emit_event(
                on_event, task_id=task_id, etype=HarnessEventType.ERROR, payload={"error": str(exc)}
            )
            return HarnessResult(
                text="",
                status=HarnessStatus.FAILED,
                error=str(exc),
                skill_id=skill_id,
                data={"runner": "DeepSeekHarnessRunner", "mode": "tool_loop"},
            )

        if self._cancel_flags.get(task_id) and self._cancel_flags[task_id].is_set():
            return HarnessResult(
                text=text,
                status=HarnessStatus.CANCELED,
                error="canceled",
                skill_id=skill_id,
                usage=usage,
                data={"runner": "DeepSeekHarnessRunner", "mode": "tool_loop"},
            )

        usage.wall_time_ms = int((time.monotonic() - started) * 1000)
        await emit_event(on_event, task_id=task_id, etype=HarnessEventType.DELTA, payload={"text": text})
        await emit_event(on_event, task_id=task_id, etype=HarnessEventType.USAGE, payload=usage.to_dict())
        await emit_event(
            on_event, task_id=task_id, etype=HarnessEventType.FINAL, payload={"state": "completed"}
        )
        return HarnessResult(
            text=text,
            status=HarnessStatus.OK,
            skill_id=skill_id,
            usage=usage,
            data={"runner": "DeepSeekHarnessRunner", "mode": "tool_loop"},
        )


__all__ = ["DeepSeekHarnessRunner"]
