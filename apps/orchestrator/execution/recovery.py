"""Phase 4 — RecoveryScheduler / worker for stale leases and offline agents."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class RecoveryScheduler:
    """Background loop: scan stale executions and recover with ownership."""

    def __init__(
        self,
        execution_service: Any,
        *,
        interval_s: float = 5.0,
        batch_size: int = 50,
        lease_seconds: float = 30.0,
        owner_id: str = "recovery-worker",
        agent_lifecycle: Any | None = None,
    ):
        self.execution = execution_service
        self.interval_s = interval_s
        self.batch_size = batch_size
        self.lease_seconds = lease_seconds
        self.owner_id = owner_id
        self.lifecycle = agent_lifecycle
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.last_run: Optional[dict[str, Any]] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="a2a-recovery", daemon=True)
        self._thread.start()
        logger.info("RecoveryScheduler started interval=%ss", self.interval_s)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        logger.info("RecoveryScheduler stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.last_run = self.tick()
            except Exception as exc:  # noqa: BLE001
                logger.exception("RecoveryScheduler tick failed: %s", exc)
            self._stop.wait(self.interval_s)

    def tick(self) -> dict[str, Any]:
        store = self.execution.store
        stale = []
        if hasattr(store, "list_stale"):
            stale = store.list_stale(stale_after_s=self.lease_seconds, limit=self.batch_size)
        recovered, contended, errors = [], [], []
        for rec in stale:
            tid = rec.task_id if hasattr(rec, "task_id") else rec.get("task_id")
            try:
                out = self.execution.recover(
                    tid,
                    stale_after_s=0,
                )
                # Attach ownership with lease when possible
                if out.get("action") == "retry" and out.get("ownership_token"):
                    if hasattr(store, "renew_lease"):
                        store.renew_lease(
                            tid,
                            out["ownership_token"],
                            lease_seconds=self.lease_seconds,
                        )
                    recovered.append({"task_id": tid, **{k: out[k] for k in ("action", "class") if k in out}})
                elif out.get("action") == "contention":
                    contended.append(tid)
                else:
                    recovered.append({"task_id": tid, "action": out.get("action")})
            except Exception as exc:  # noqa: BLE001
                errors.append({"task_id": tid, "error": str(exc)})

        offline_agents = []
        if self.lifecycle and hasattr(self.lifecycle, "mark_stale_offline"):
            offline_agents = self.lifecycle.mark_stale_offline()

        result = {
            "scanned": len(stale),
            "recovered": recovered,
            "contended": contended,
            "errors": errors,
            "offline_agents": offline_agents,
            "ts": time.time(),
        }
        if recovered or errors:
            logger.info("RecoveryScheduler tick %s", result)
        return result


__all__ = ["RecoveryScheduler"]
