"""Phase 3 — retry / timeout helpers (pure policy math + terminal protection)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    retryable_errors: tuple[str, ...] = (
        "TIMEOUT",
        "UNAVAILABLE",
        "CONNECTION_ERROR",
        "UNKNOWN",
        "RETRYABLE",
    )

    def backoff(self, attempt: int) -> float:
        """Exponential backoff: base * 2^attempt, capped."""
        delay = self.base_delay_s * (2 ** max(0, attempt))
        return min(delay, self.max_delay_s)

    def should_retry(self, attempt: int, error_code: Optional[str] = None) -> bool:
        if attempt >= self.max_retries:
            return False
        if error_code is None:
            return True
        return error_code.upper() in {e.upper() for e in self.retryable_errors}


@dataclass
class TimeoutPolicy:
    task_timeout_s: float = 300.0
    delegation_timeout_s: float = 120.0
    agent_timeout_s: float = 60.0

    def exceeded(self, elapsed_s: float, *, kind: str = "task") -> bool:
        limit = {
            "task": self.task_timeout_s,
            "delegation": self.delegation_timeout_s,
            "agent": self.agent_timeout_s,
        }.get(kind, self.task_timeout_s)
        return elapsed_s > limit


__all__ = ["RetryPolicy", "TimeoutPolicy"]
