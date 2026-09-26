"""Windows-safe subprocess supervision for harness CLI runners."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Optional

logger = logging.getLogger(__name__)


class ManagedProcess:
    """Track one child process with cancel + timeout helpers."""

    def __init__(self, proc: asyncio.subprocess.Process, *, task_id: str):
        self.proc = proc
        self.task_id = task_id
        self._killed = False

    @property
    def pid(self) -> Optional[int]:
        return self.proc.pid

    @property
    def returncode(self) -> Optional[int]:
        return self.proc.returncode

    def alive(self) -> bool:
        return self.proc.returncode is None

    async def kill_tree(self, *, grace_s: float = 2.0) -> bool:
        """Terminate then hard-kill the process (and children on Windows)."""
        if not self.alive():
            return False
        self._killed = True
        pid = self.proc.pid
        try:
            if sys.platform == "win32" and pid:
                # /T kills the whole tree — avoids zombie Claude CLI children.
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/PID",
                    str(pid),
                    "/T",
                    "/F",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.wait()
            else:
                try:
                    self.proc.terminate()
                except ProcessLookupError:
                    return True
                try:
                    await asyncio.wait_for(self.proc.wait(), timeout=grace_s)
                except asyncio.TimeoutError:
                    try:
                        if hasattr(os, "killpg"):
                            os.killpg(os.getpgid(pid), signal.SIGKILL)  # type: ignore[arg-type]
                        else:
                            self.proc.kill()
                    except (ProcessLookupError, OSError):
                        pass
                    try:
                        await asyncio.wait_for(self.proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        logger.warning("process %s still alive after kill", pid)
        except Exception as exc:  # noqa: BLE001
            logger.debug("kill_tree failed for %s: %s", self.task_id, exc)
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
        return True


class ProcessSupervisor:
    """Map task_id → ManagedProcess for cancel fan-out."""

    def __init__(self):
        self._procs: dict[str, ManagedProcess] = {}
        self._lock = asyncio.Lock()

    async def register(self, task_id: str, proc: asyncio.subprocess.Process) -> ManagedProcess:
        mp = ManagedProcess(proc, task_id=task_id)
        async with self._lock:
            old = self._procs.pop(task_id, None)
            self._procs[task_id] = mp
        if old and old.alive():
            await old.kill_tree()
        return mp

    async def unregister(self, task_id: str) -> None:
        async with self._lock:
            self._procs.pop(task_id, None)

    async def cancel(self, task_id: str) -> bool:
        async with self._lock:
            mp = self._procs.get(task_id)
        if mp is None:
            return False
        ok = await mp.kill_tree()
        await self.unregister(task_id)
        return ok

    async def spawn(
        self,
        task_id: str,
        *argv: str,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
    ) -> ManagedProcess:
        kwargs: dict = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "env": env or os.environ.copy(),
        }
        if cwd:
            kwargs["cwd"] = cwd
        if sys.platform != "win32":
            # New session so we can kill the process group on cancel.
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec(*argv, **kwargs)
        # Raise StreamReader limits — CLI JSONL tool payloads often exceed 64KiB.
        try:
            from .runners._cli_common import bump_stream_limit

            bump_stream_limit(proc.stdout)
            bump_stream_limit(proc.stderr)
        except Exception:  # noqa: BLE001
            pass
        return await self.register(task_id, proc)


__all__ = ["ManagedProcess", "ProcessSupervisor"]
