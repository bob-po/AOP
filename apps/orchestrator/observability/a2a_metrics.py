"""Phase 3 — a2a_* Prometheus metrics (extends existing observability stack)."""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram

    PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    PROM_AVAILABLE = False

    class _N:
        def labels(self, *a, **k):
            return self

        def inc(self, *a, **k):
            pass

        def dec(self, *a, **k):
            pass

        def set(self, *a, **k):
            pass

        def observe(self, *a, **k):
            pass

    def Counter(*a, **k):  # type: ignore
        return _N()

    def Gauge(*a, **k):  # type: ignore
        return _N()

    def Histogram(*a, **k):  # type: ignore
        return _N()


a2a_tasks_total = Counter("a2a_tasks_total", "A2A tasks by state", ["state"])
a2a_tasks_active = Gauge("a2a_tasks_active", "Active A2A tasks")
a2a_tasks_failed = Counter("a2a_tasks_failed", "Failed A2A tasks")
a2a_tasks_timeout = Counter("a2a_tasks_timeout", "Timed-out A2A tasks")

a2a_delegations_total = Counter("a2a_delegations_total", "A2A delegations", ["state"])
a2a_delegations_active = Gauge("a2a_delegations_active", "Active delegations")
a2a_delegations_failed = Counter("a2a_delegations_failed", "Failed delegations")
a2a_delegations_retry = Counter("a2a_delegations_retry", "Delegation retries")

a2a_agent_active_tasks = Gauge("a2a_agent_active_tasks", "Active tasks per agent", ["agent_id"])
a2a_agent_requests_total = Counter(
    "a2a_agent_requests_total", "Agent requests", ["agent_id", "status"]
)

a2a_task_duration_seconds = Histogram("a2a_task_duration_seconds", "Task duration seconds")
a2a_delegation_duration_seconds = Histogram(
    "a2a_delegation_duration_seconds", "Delegation duration seconds"
)

a2a_governance_denied_total = Counter(
    "a2a_governance_denied_total", "Governance denials", ["code"]
)
a2a_governance_quota_exhausted_total = Counter(
    "a2a_governance_quota_exhausted_total", "Quota exhausted denials"
)

# Phase 6 — Marketplace / Skill discovery
agent_registration_count = Counter("agent_registration_count", "Agent manifest registrations")
agent_install_count = Counter("agent_install_count", "Agent marketplace installs")
agent_activation_count = Counter("agent_activation_count", "Agent activations")
skill_discovery_count = Counter("skill_discovery_count", "Skill discovery queries")
skill_invocation_count = Counter("skill_invocation_count", "Skill-based invocations")
installation_failure_count = Counter("installation_failure_count", "Failed marketplace installs")
discovery_latency = Histogram("discovery_latency", "Skill/agent discovery latency seconds")


def observe_execution_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    payload = payload or {}
    if event_type == "task.created":
        a2a_tasks_total.labels(state="PENDING").inc()
        a2a_tasks_active.inc()
    elif event_type == "task.started":
        a2a_tasks_total.labels(state="RUNNING").inc()
    elif event_type == "task.completed":
        a2a_tasks_total.labels(state="SUCCEEDED").inc()
        a2a_tasks_active.dec()
        if payload.get("duration_ms"):
            a2a_task_duration_seconds.observe(float(payload["duration_ms"]) / 1000.0)
    elif event_type == "task.failed":
        a2a_tasks_failed.inc()
        a2a_tasks_total.labels(state="FAILED").inc()
        a2a_tasks_active.dec()
    elif event_type == "task.timeout":
        a2a_tasks_timeout.inc()
        a2a_tasks_total.labels(state="TIMEOUT").inc()
        a2a_tasks_active.dec()
    elif event_type == "task.cancelled":
        a2a_tasks_total.labels(state="CANCELLED").inc()
        a2a_tasks_active.dec()
    elif event_type == "task.retrying":
        a2a_delegations_retry.inc()
    elif event_type == "delegation.requested":
        a2a_delegations_total.labels(state="PENDING").inc()
        a2a_delegations_active.inc()
    elif event_type == "delegation.completed":
        a2a_delegations_total.labels(state="SUCCEEDED").inc()
        a2a_delegations_active.dec()
    elif event_type == "delegation.failed":
        a2a_delegations_failed.inc()
        a2a_delegations_active.dec()


def observe_governance_denial(code: str) -> None:
    a2a_governance_denied_total.labels(code=code or "UNKNOWN").inc()
    if code in {"QUOTA_EXCEEDED", "CALL_LIMIT_EXCEEDED", "BUDGET_EXCEEDED", "CONCURRENCY_LIMIT_EXCEEDED"}:
        a2a_governance_quota_exhausted_total.inc()


def observe_marketplace_event(event_type: str, payload: dict[str, Any] | None = None) -> None:
    payload = payload or {}
    if event_type == "AGENT_REGISTERED":
        agent_registration_count.inc()
    elif event_type == "AGENT_INSTALLED":
        agent_install_count.inc()
    elif event_type == "AGENT_ACTIVATED":
        agent_activation_count.inc()
    elif event_type == "SKILL_PUBLISHED" or event_type == "skill.discovery":
        skill_discovery_count.inc()
    elif event_type == "skill.invocation":
        skill_invocation_count.inc()
    elif event_type == "installation.failed":
        installation_failure_count.inc()
    latency = payload.get("latency_ms") or payload.get("latency")
    if latency is not None:
        discovery_latency.observe(float(latency) / (1000.0 if float(latency) > 10 else 1.0))


__all__ = [
    "observe_execution_event",
    "observe_governance_denial",
    "observe_marketplace_event",
    "a2a_tasks_total",
    "a2a_tasks_active",
    "a2a_tasks_failed",
    "a2a_tasks_timeout",
    "a2a_delegations_total",
    "a2a_delegations_active",
    "a2a_delegations_failed",
    "a2a_delegations_retry",
    "a2a_agent_active_tasks",
    "a2a_agent_requests_total",
    "a2a_task_duration_seconds",
    "a2a_delegation_duration_seconds",
    "a2a_governance_denied_total",
    "a2a_governance_quota_exhausted_total",
    "agent_registration_count",
    "agent_install_count",
    "agent_activation_count",
    "skill_discovery_count",
    "skill_invocation_count",
    "installation_failure_count",
    "discovery_latency",
]
