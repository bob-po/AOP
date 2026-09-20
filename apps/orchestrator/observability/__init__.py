"""Lightweight observability snapshots for the control plane."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row
from db import connect

try:
    from prometheus_client import Counter, Histogram, Gauge, start_http_server, generate_latest
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    generate_latest = None

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Create dummy metric class when prometheus_client is not available
class DummyMetric:
    def __init__(self, *args, **kwargs):
        pass
    def inc(self, *args, **kwargs):
        pass
    def dec(self, *args, **kwargs):
        pass
    def set(self, *args, **kwargs):
        pass
    def observe(self, *args, **kwargs):
        pass
    def labels(self, *args, **kwargs):
        return self
    def time(self, *args, **kwargs):
        def decorator(f):
            return f
        return decorator

# Initialize metrics based on availability
if PROMETHEUS_AVAILABLE:
    task_counter = Counter('aop_tasks_total', 'Total tasks created', ['status'])
    task_duration = Histogram('aop_task_duration_seconds', 'Task execution duration')
    active_tasks = Gauge('aop_active_tasks', 'Currently active tasks')
    agent_counter = Counter('aop_agent_calls_total', 'Total agent calls', ['agent', 'status'])
    agent_latency = Histogram('aop_agent_latency_seconds', 'Agent call latency', ['agent'])
    agent_errors = Counter('aop_agent_errors_total', 'Total agent errors', ['agent', 'error_type'])
    queue_size = Gauge('aop_queue_size', 'Current queue size')
    memory_usage = Gauge('aop_memory_usage_bytes', 'Memory usage in bytes')
else:
    task_counter = DummyMetric('aop_tasks_total', 'Total tasks created', ['status'])
    task_duration = DummyMetric('aop_task_duration_seconds', 'Task execution duration')
    active_tasks = DummyMetric('aop_active_tasks', 'Currently active tasks')
    agent_counter = DummyMetric('aop_agent_calls_total', 'Total agent calls', ['agent', 'status'])
    agent_latency = DummyMetric('aop_agent_latency_seconds', 'Agent call latency', ['agent'])
    agent_errors = DummyMetric('aop_agent_errors_total', 'Total agent errors', ['agent', 'error_type'])
    queue_size = DummyMetric('aop_queue_size', 'Current queue size')
    memory_usage = DummyMetric('aop_memory_usage_bytes', 'Memory usage in bytes')


def record_task_created(status: str = "running") -> None:
    task_counter.labels(status=status).inc()
    active_tasks.inc()


def record_task_finished(status: str, duration_seconds: float | None = None) -> None:
    task_counter.labels(status=status).inc()
    try:
        active_tasks.dec()
    except Exception:  # noqa: BLE001
        pass
    if duration_seconds is not None and duration_seconds >= 0:
        task_duration.observe(duration_seconds)


def record_agent_call(
    agent: str,
    *,
    status: str,
    latency_seconds: float | None = None,
    error_type: str | None = None,
) -> None:
    key = (agent or "unknown").strip() or "unknown"
    agent_counter.labels(agent=key, status=status).inc()
    if latency_seconds is not None and latency_seconds >= 0:
        agent_latency.labels(agent=key).observe(latency_seconds)
    if status != "success" and error_type:
        agent_errors.labels(agent=key, error_type=error_type[:64]).inc()


def set_queue_size(n: int) -> None:
    queue_size.set(max(0, int(n)))


def start_metrics_server(port: int = 9091):
    """Start Prometheus metrics server if available."""
    if PROMETHEUS_AVAILABLE:
        try:
            start_http_server(port)
            return True
        except Exception as e:
            print(f"Failed to start metrics server: {e}")
            return False
    return False

def get_metrics_text() -> str:
    """Get Prometheus metrics text format."""
    if PROMETHEUS_AVAILABLE and generate_latest:
        return generate_latest().decode('utf-8')
    return "# Metrics not available (prometheus-client not installed)\n"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MetricsService:
    def __init__(
        self,
        database_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.tenant_id = tenant_id

    def snapshot(self, *, hours: float = 24) -> dict[str, Any]:
        since = _utc_now() - timedelta(hours=max(1.0, float(hours)))
        with connect(self.database_url) as conn:
            tasks = conn.execute(
                """
                SELECT
                  COUNT(*)::int AS total,
                  COUNT(*) FILTER (WHERE status = 'running')::int AS running,
                  COUNT(*) FILTER (WHERE status = 'waiting_for_user')::int AS waiting_for_user,
                  COUNT(*) FILTER (WHERE status = 'completed')::int AS completed,
                  COUNT(*) FILTER (WHERE status = 'failed')::int AS failed,
                  COUNT(*) FILTER (WHERE status = 'cancelled')::int AS cancelled,
                  COUNT(*) FILTER (WHERE created_at >= %s)::int AS created_window
                FROM tasks
                WHERE tenant_id = %s::uuid
                """,
                (since, self.tenant_id),
            ).fetchone()
            agents = conn.execute(
                """
                SELECT
                  COUNT(*)::int AS total,
                  COUNT(*) FILTER (WHERE status IN ('online','running'))::int AS online,
                  COUNT(*) FILTER (WHERE status = 'degraded')::int AS degraded,
                  COUNT(*) FILTER (WHERE status = 'offline')::int AS offline,
                  COUNT(*) FILTER (WHERE status = 'disabled')::int AS disabled
                FROM agents
                WHERE tenant_id = %s::uuid
                """,
                (self.tenant_id,),
            ).fetchone()
            runs = conn.execute(
                """
                SELECT
                  COUNT(*)::int AS total,
                  COUNT(*) FILTER (WHERE status = 'success')::int AS success,
                  COUNT(*) FILTER (WHERE status = 'failed')::int AS failed,
                  COALESCE(AVG(latency_ms) FILTER (WHERE latency_ms IS NOT NULL), 0)::float
                    AS avg_latency_ms
                FROM agent_runs
                WHERE tenant_id = %s::uuid AND created_at >= %s
                """,
                (self.tenant_id, since),
            ).fetchone()
            memories = conn.execute(
                """
                SELECT COUNT(*)::int AS total
                FROM task_memories
                WHERE tenant_id = %s::uuid
                """,
                (self.tenant_id,),
            ).fetchone()
            tenant_memories = conn.execute(
                """
                SELECT COUNT(*)::int AS total
                FROM tenant_memories
                WHERE tenant_id = %s::uuid
                """,
                (self.tenant_id,),
            ).fetchone()
            evals = conn.execute(
                """
                SELECT COUNT(*)::int AS total,
                       COALESCE(AVG(score), 0)::float AS avg_score
                FROM task_evaluations
                WHERE tenant_id = %s::uuid AND created_at >= %s
                """,
                (self.tenant_id, since),
            ).fetchone()

        run_total = int((runs or {}).get("total") or 0)
        run_ok = int((runs or {}).get("success") or 0)
        return {
            "generated_at": _utc_now().isoformat(),
            "window_hours": hours,
            "tasks": dict(tasks or {}),
            "agents": dict(agents or {}),
            "agent_runs": {
                **dict(runs or {}),
                "success_rate": round((run_ok / run_total) if run_total else 0.0, 4),
            },
            "memories": dict(memories or {}),
            "tenant_memories": dict(tenant_memories or {}),
            "evaluations": dict(evals or {}),
        }

    def prometheus_text(self, *, hours: float = 24) -> str:
        snap = self.snapshot(hours=hours)
        lines = [
            "# HELP aop_tasks Task counts by status",
            "# TYPE aop_tasks gauge",
        ]
        for k, v in (snap.get("tasks") or {}).items():
            if isinstance(v, (int, float)):
                lines.append(f'aop_tasks{{status="{k}"}} {v}')
        lines += [
            "# HELP aop_agents Agent counts by status",
            "# TYPE aop_agents gauge",
        ]
        for k, v in (snap.get("agents") or {}).items():
            if isinstance(v, (int, float)):
                lines.append(f'aop_agents{{status="{k}"}} {v}')
        ar = snap.get("agent_runs") or {}
        lines += [
            "# HELP aop_agent_runs_total Agent runs in window",
            "# TYPE aop_agent_runs_total counter",
            f"aop_agent_runs_total {ar.get('total') or 0}",
            "# HELP aop_agent_run_success_rate Success rate in window",
            "# TYPE aop_agent_run_success_rate gauge",
            f"aop_agent_run_success_rate {ar.get('success_rate') or 0}",
            "# HELP aop_agent_run_avg_latency_ms Average latency ms",
            "# TYPE aop_agent_run_avg_latency_ms gauge",
            f"aop_agent_run_avg_latency_ms {ar.get('avg_latency_ms') or 0}",
            "# HELP aop_task_memories_total Task memory entries",
            "# TYPE aop_task_memories_total gauge",
            f"aop_task_memories_total {(snap.get('memories') or {}).get('total') or 0}",
            "# HELP aop_tenant_memories_total Tenant long-term memory entries",
            "# TYPE aop_tenant_memories_total gauge",
            f"aop_tenant_memories_total {(snap.get('tenant_memories') or {}).get('total') or 0}",
        ]
        return "\n".join(lines) + "\n"
