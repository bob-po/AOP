"""Phase 17: observability helpers increment counters."""

from __future__ import annotations

from observability import (
    get_metrics_text,
    record_agent_call,
    record_task_created,
    record_task_finished,
)


def test_record_helpers_emit_prometheus_text():
    record_task_created("running")
    record_agent_call("search-agent", status="success", latency_seconds=0.12)
    record_agent_call("rag-agent", status="failed", error_type="timeout")
    record_task_finished("completed", duration_seconds=1.5)
    text = get_metrics_text()
    assert "aop_tasks_total" in text or "Metrics not available" in text
    if "Metrics not available" not in text:
        assert "aop_agent_calls_total" in text
        assert 'agent="search-agent"' in text or "search-agent" in text
