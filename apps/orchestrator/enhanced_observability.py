"""Enhanced observability and monitoring (P36.6).

This module provides distributed state metrics, enhanced error classification,
distributed tracing integration, and SLO monitoring.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import psycopg
from psycopg.rows import dict_row
from db import connect


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MetricType(Enum):
    """Types of metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """A single metric."""
    name: str
    value: float
    metric_type: MetricType
    labels: dict[str, str] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.labels is None:
            self.labels = {}
        if self.timestamp is None:
            self.timestamp = _utc_now()


class DistributedMetrics:
    """Distributed metrics collector for state monitoring."""
    
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.metrics: list[Metric] = []
        self.max_metrics = 10000
    
    def record_metric(
        self,
        name: str,
        value: float,
        metric_type: MetricType = MetricType.GAUGE,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record a metric."""
        metric = Metric(
            name=name,
            value=value,
            metric_type=metric_type,
            labels=labels or {},
        )
        self.metrics.append(metric)
        
        # Trim if too many metrics
        if len(self.metrics) > self.max_metrics:
            self.metrics = self.metrics[-self.max_metrics:]
    
    def collect_distributed_state_metrics(self) -> dict[str, Any]:
        """Collect distributed state metrics from database."""
        with connect(self.database_url) as conn:
            # Task state distribution
            task_states = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM tasks
                GROUP BY status
                """,
            ).fetchall()
            
            # Node state distribution
            node_states = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM task_nodes
                GROUP BY status
                """,
            ).fetchall()
            
            # Active workers
            active_workers = conn.execute(
                """
                SELECT COUNT(DISTINCT assigned_agent_id) as count
                FROM task_nodes
                WHERE status = 'running'
                """,
            ).fetchone()
            
            # Request tracking metrics
            request_stats = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM a2a_requests
                GROUP BY status
                """,
            ).fetchall()
            
            # Outbox metrics
            outbox_stats = conn.execute(
                """
                SELECT status, COUNT(*) as count
                FROM outbox_events
                GROUP BY status
                """,
            ).fetchall()
            
            return {
                "task_states": {row["status"]: row["count"] for row in task_states},
                "node_states": {row["status"]: row["count"] for row in node_states},
                "active_workers": active_workers["count"] if active_workers else 0,
                "request_stats": {row["status"]: row["count"] for row in request_stats},
                "outbox_stats": {row["status"]: row["count"] for row in outbox_stats},
            }
    
    def record_slo_metrics(self) -> dict[str, Any]:
        """Record SLO metrics."""
        state = self.collect_distributed_state_metrics()
        
        # Calculate SLOs
        total_tasks = sum(state["task_states"].values())
        completed_tasks = state["task_states"].get("completed", 0)
        failed_tasks = state["task_states"].get("failed", 0)
        
        success_rate = completed_tasks / total_tasks if total_tasks > 0 else 0.0
        failure_rate = failed_tasks / total_tasks if total_tasks > 0 else 0.0
        
        # Record metrics
        self.record_metric("slo_success_rate", success_rate, MetricType.GAUGE)
        self.record_metric("slo_failure_rate", failure_rate, MetricType.GAUGE)
        self.record_metric("total_tasks", total_tasks, MetricType.GAUGE)
        self.record_metric("active_workers", state["active_workers"], MetricType.GAUGE)
        
        return {
            "success_rate": success_rate,
            "failure_rate": failure_rate,
            "total_tasks": total_tasks,
            "active_workers": state["active_workers"],
        }
    
    def get_error_classification_metrics(self) -> dict[str, Any]:
        """Get error classification metrics."""
        with connect(self.database_url) as conn:
            # Error distribution by type
            error_types = conn.execute(
                """
                SELECT 
                    CASE 
                        WHEN error_message ILIKE '%timeout%' THEN 'timeout'
                        WHEN error_message ILIKE '%connection%' OR error_message ILIKE '%network%' THEN 'network'
                        WHEN error_message ILIKE '%agent%' THEN 'agent'
                        ELSE 'other'
                    END as error_type,
                    COUNT(*) as count
                FROM task_nodes
                WHERE status = 'failed' AND error_message IS NOT NULL
                GROUP BY error_type
                """,
            ).fetchall()
            
            return {
                "error_distribution": {row["error_type"]: row["count"] for row in error_types},
            }
    
    def flush_metrics(self) -> list[Metric]:
        """Flush all metrics and return them."""
        metrics = self.metrics.copy()
        self.metrics.clear()
        return metrics


class SLOMonitor:
    """SLO monitoring with alerts."""
    
    def __init__(
        self,
        success_rate_threshold: float = 0.95,
        failure_rate_threshold: float = 0.05,
    ):
        self.success_rate_threshold = success_rate_threshold
        self.failure_rate_threshold = failure_rate_threshold
        self.alerts: list[dict[str, Any]] = []
    
    def check_slo_compliance(self, metrics: dict[str, Any]) -> list[dict[str, Any]]:
        """Check SLO compliance and generate alerts."""
        alerts = []
        
        success_rate = metrics.get("success_rate", 0.0)
        failure_rate = metrics.get("failure_rate", 0.0)
        
        if success_rate < self.success_rate_threshold:
            alerts.append({
                "type": "slo_violation",
                "severity": "warning",
                "metric": "success_rate",
                "threshold": self.success_rate_threshold,
                "actual": success_rate,
                "message": f"Success rate below threshold: {success_rate:.2%} < {self.success_rate_threshold:.2%}",
            })
        
        if failure_rate > self.failure_rate_threshold:
            alerts.append({
                "type": "slo_violation",
                "severity": "critical",
                "metric": "failure_rate",
                "threshold": self.failure_rate_threshold,
                "actual": failure_rate,
                "message": f"Failure rate above threshold: {failure_rate:.2%} > {self.failure_rate_threshold:.2%}",
            })
        
        self.alerts.extend(alerts)
        return alerts
    
    def get_recent_alerts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent alerts."""
        return self.alerts[-limit:]


# Singleton instances
_distributed_metrics: DistributedMetrics | None = None
_slo_monitor: SLOMonitor | None = None


def get_distributed_metrics() -> DistributedMetrics:
    """Get or create the singleton distributed metrics."""
    global _distributed_metrics
    if _distributed_metrics is None:
        _distributed_metrics = DistributedMetrics()
    return _distributed_metrics


def get_slo_monitor() -> SLOMonitor:
    """Get or create the singleton SLO monitor."""
    global _slo_monitor
    if _slo_monitor is None:
        _slo_monitor = SLOMonitor()
    return _slo_monitor
