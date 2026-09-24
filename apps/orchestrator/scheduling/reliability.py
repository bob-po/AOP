"""Phase 5.7 — Agent reliability rollups from Execution Records (read-only SoT)."""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class AgentReliability:
    agent_id: str
    success_rate: float = 0.0
    failure_rate: float = 0.0
    timeout_rate: float = 0.0
    retry_rate: float = 0.0
    average_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    recent_failures: int = 0
    availability: float = 1.0
    sample_size: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


class ReliabilityService:
    """Derive stats from execution store snapshots — never mutates Execution Record."""

    def __init__(self):
        self._lock = threading.RLock()
        self._cache: dict[str, AgentReliability] = {}

    def compute_from_records(self, records: list[Any]) -> dict[str, AgentReliability]:
        by_agent: dict[str, list[Any]] = {}
        for rec in records:
            aid = getattr(rec, "agent_id", None) or (rec.get("agent_id") if isinstance(rec, dict) else None)
            if not aid:
                continue
            by_agent.setdefault(str(aid), []).append(rec)

        out: dict[str, AgentReliability] = {}
        for aid, rows in by_agent.items():
            n = len(rows)
            succ = fail = timeout = retry = 0
            latencies: list[float] = []
            for r in rows:
                state = getattr(r, "state", None) or (r.get("state") if isinstance(r, dict) else "")
                dur = getattr(r, "duration_ms", None)
                if dur is None and isinstance(r, dict):
                    dur = r.get("duration_ms") or 0
                attempt = getattr(r, "attempt", None)
                if attempt is None and isinstance(r, dict):
                    attempt = r.get("attempt") or 0
                state = str(state or "")
                if state == "SUCCEEDED":
                    succ += 1
                elif state == "FAILED":
                    fail += 1
                elif state == "TIMEOUT":
                    timeout += 1
                if int(attempt or 0) > 0:
                    retry += 1
                if dur:
                    latencies.append(float(dur))
            latencies.sort()
            recent_fail = sum(
                1
                for r in rows[-10:]
                if str(
                    getattr(r, "state", None)
                    or (r.get("state") if isinstance(r, dict) else "")
                )
                in {"FAILED", "TIMEOUT"}
            )
            avail = 1.0 - (timeout + fail) / n if n else 1.0
            out[aid] = AgentReliability(
                agent_id=aid,
                success_rate=succ / n if n else 0.0,
                failure_rate=fail / n if n else 0.0,
                timeout_rate=timeout / n if n else 0.0,
                retry_rate=retry / n if n else 0.0,
                average_latency_ms=(sum(latencies) / len(latencies)) if latencies else 0.0,
                p95_latency_ms=_percentile(latencies, 0.95),
                p99_latency_ms=_percentile(latencies, 0.99),
                recent_failures=recent_fail,
                availability=max(0.0, min(1.0, avail)),
                sample_size=n,
            )
        with self._lock:
            self._cache.update(out)
        return out

    def get(self, agent_id: str) -> Optional[AgentReliability]:
        with self._lock:
            return self._cache.get(agent_id)

    def score(self, agent_id: str, *, cold_start: float = 0.85) -> float:
        rel = self.get(agent_id)
        if not rel or rel.sample_size == 0:
            return cold_start
        # Blend success + availability − timeout penalty
        return max(
            0.0,
            min(
                1.0,
                0.5 * rel.success_rate
                + 0.3 * rel.availability
                + 0.2 * (1.0 - rel.timeout_rate),
            ),
        )


__all__ = ["AgentReliability", "ReliabilityService"]
