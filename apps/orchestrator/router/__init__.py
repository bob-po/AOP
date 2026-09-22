"""Router v3: Skill Match + Online + configurable scored selection (latency / success / priority)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from db import connect

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None  # type: ignore

from .scoring import ScoringEngine, ScoringPolicy


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"
ONLINE_STATUSES = frozenset({"online", "running"})

# Optional: Import CandidateFilter for advanced filtering
try:
    from .filter import CandidateFilter, TaskRequirements, RoutingPolicy
    HAS_FILTER = True
except ImportError:  # pragma: no cover
    HAS_FILTER = False


@dataclass
class RoutedAgent:
    agent_id: str
    agent_key: str
    name: str
    endpoint: str
    status: str
    skills: list[str]
    priority: int
    source: str  # redis+pg | pg
    score: float = 0.0
    score_breakdown: dict[str, float] = field(default_factory=dict)


class RouterError(LookupError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AgentRouter:
    """Select an online agent that provides the requested skill (scored)."""

    def __init__(
        self,
        database_url: str | None = None,
        redis_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
        *,
        metrics_window_hours: float | None = None,
        scoring_policy: ScoringPolicy | None = None,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.tenant_id = tenant_id
        self.metrics_window_hours = float(
            metrics_window_hours
            if metrics_window_hours is not None
            else os.getenv("ROUTER_METRICS_HOURS", "24")
        )
        self.smart = os.getenv("ROUTER_SMART", "true").lower() not in {"0", "false", "no"}
        self._redis = None
        if redis is not None:
            try:
                self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True)
                self._redis.ping()
            except Exception:  # noqa: BLE001
                self._redis = None
        
        # Initialize scoring engine with configurable policy
        self._scoring_policy = scoring_policy or ScoringPolicy.from_env()
        self._scoring_engine = ScoringEngine(self._scoring_policy)

    @property
    def scoring_policy(self) -> ScoringPolicy:
        """Get the current scoring policy."""
        return self._scoring_policy

    def select(
        self,
        skill: str,
        *,
        exclude_agent_ids: set[str] | list[str] | None = None,
    ) -> RoutedAgent:
        ranked = self.rank(skill, exclude_agent_ids=exclude_agent_ids)
        if not ranked:
            excluded = {str(x) for x in (exclude_agent_ids or []) if x}
            raise RouterError(
                f"no online agent for skill={skill!r}"
                + (f" after excluding {sorted(excluded)}" if excluded else "")
            )
        return ranked[0]

    def rank(
        self,
        skill: str,
        *,
        exclude_agent_ids: set[str] | list[str] | None = None,
    ) -> list[RoutedAgent]:
        skill = (skill or "").strip()
        if not skill:
            raise RouterError("skill is required")

        excluded = {str(x) for x in (exclude_agent_ids or []) if x}
        candidates = self._candidates_from_redis(skill)
        source = "redis+pg"
        if not candidates:
            candidates = self._candidates_from_pg(skill)
            source = "pg"

        online = [
            c
            for c in candidates
            if c["status"] in ONLINE_STATUSES
            and c.get("endpoint")
            and c["agent_id"] not in excluded
        ]
        if not online:
            return []

        metrics = self._load_metrics([c["agent_id"] for c in online])
        scored: list[RoutedAgent] = []
        for c in online:
            breakdown = self._score(c, metrics.get(c["agent_id"]) or {})
            total = float(breakdown["total"])
            scored.append(
                RoutedAgent(
                    agent_id=c["agent_id"],
                    agent_key=c["agent_key"],
                    name=c["name"],
                    endpoint=c["endpoint"],
                    status=c["status"],
                    skills=list(c.get("skills") or []),
                    priority=int(c["priority"]),
                    source=source,
                    score=round(total, 4),
                    score_breakdown={k: round(v, 4) for k, v in breakdown.items()},
                )
            )

        if self.smart:
            scored.sort(key=lambda a: (-a.score, a.priority, a.name))
        else:
            scored.sort(key=lambda a: (a.priority, a.name))
        return scored

    def preview(
        self,
        skill: str,
        *,
        exclude_agent_ids: set[str] | list[str] | None = None,
    ) -> dict[str, Any]:
        ranked = self.rank(skill, exclude_agent_ids=exclude_agent_ids)
        return {
            "skill": skill,
            "smart": self.smart,
            "metrics_window_hours": self.metrics_window_hours,
            "scoring_policy": self._scoring_policy.to_dict(),
            "candidates": [
                {
                    "agent_id": a.agent_id,
                    "agent_key": a.agent_key,
                    "name": a.name,
                    "status": a.status,
                    "endpoint": a.endpoint,
                    "priority": a.priority,
                    "score": a.score,
                    "score_breakdown": a.score_breakdown,
                    "source": a.source,
                }
                for a in ranked
            ],
            "selected": ranked[0].agent_id if ranked else None,
        }

    def agent_performance(self, *, limit: int = 50) -> list[dict[str, Any]]:
        since = _utc_now() - timedelta(hours=self.metrics_window_hours)
        sql = """
            SELECT a.id::text AS agent_id,
                   a.agent_key,
                   a.name,
                   a.status,
                   a.priority,
                   COUNT(r.id)::int AS request_count,
                   COUNT(r.id) FILTER (WHERE r.status = 'success')::int AS success_count,
                   COUNT(r.id) FILTER (WHERE r.status = 'failed')::int AS failure_count,
                   COALESCE(AVG(r.latency_ms) FILTER (WHERE r.latency_ms IS NOT NULL), 0)::float
                     AS avg_latency_ms
            FROM agents a
            LEFT JOIN agent_runs r
              ON r.agent_id = a.id AND r.created_at >= %s
            WHERE a.tenant_id = %s::uuid
            GROUP BY a.id
            ORDER BY request_count DESC, a.name ASC
            LIMIT %s
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (since, self.tenant_id, max(1, min(limit, 200)))).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            req = int(r["request_count"] or 0)
            ok = int(r["success_count"] or 0)
            out.append(
                {
                    **dict(r),
                    "success_rate": round((ok / req) if req else 0.0, 4),
                }
            )
        return out

    def _score(self, candidate: dict[str, Any], metrics: dict[str, Any]) -> dict[str, float]:
        """Score a candidate using the configurable scoring engine.

        Args:
            candidate: Agent candidate dictionary
            metrics: Agent metrics from agent_runs

        Returns:
            Dictionary with individual scores and total score
        """
        # Use new configurable scoring engine
        scores = self._scoring_engine.score_candidate(candidate, metrics)
        
        # Add sample count and latency for backward compatibility
        req = int(metrics.get("request_count") or 0)
        avg_lat = float(metrics.get("avg_latency_ms") or 0.0)
        scores["samples"] = float(req)
        scores["avg_latency_ms"] = avg_lat
        
        # For backward compatibility with smart=false mode
        if not self.smart:
            priority_score = scores["priority"]
            scores["total"] = priority_score
        
        return scores

    def _load_metrics(self, agent_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not agent_ids:
            return {}
        since = _utc_now() - timedelta(hours=self.metrics_window_hours)
        sql = """
            SELECT agent_id::text AS agent_id,
                   COUNT(*)::int AS request_count,
                   COUNT(*) FILTER (WHERE status = 'success')::int AS success_count,
                   COUNT(*) FILTER (WHERE status = 'failed')::int AS failure_count,
                   COALESCE(AVG(latency_ms) FILTER (WHERE latency_ms IS NOT NULL), 0)::float
                     AS avg_latency_ms
            FROM agent_runs
            WHERE agent_id = ANY(%s::uuid[])
              AND created_at >= %s
            GROUP BY agent_id
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (agent_ids, since)).fetchall()
        return {r["agent_id"]: dict(r) for r in rows}

    def _candidates_from_redis(self, skill: str) -> list[dict[str, Any]]:
        if self._redis is None:
            return []
        agent_ids = list(self._redis.smembers(f"agent:skill:{skill}") or [])
        if not agent_ids:
            return []
        out: list[dict[str, Any]] = []
        for agent_id in agent_ids:
            row = self._get_agent(agent_id)
            if row and skill in (row.get("skills") or []):
                out.append(row)
        return out

    def _candidates_from_pg(self, skill: str) -> list[dict[str, Any]]:
        sql = """
            SELECT a.id::text AS agent_id,
                   a.agent_key,
                   a.name,
                   a.status,
                   a.priority,
                   COALESCE((
                     SELECT e.url FROM agent_endpoints e
                     WHERE e.agent_id = a.id AND e.is_primary = true
                     ORDER BY e.updated_at DESC LIMIT 1
                   ), '') AS endpoint,
                   COALESCE((
                     SELECT array_agg(s.skill_id ORDER BY s.skill_id)
                     FROM agent_skills s WHERE s.agent_id = a.id
                   ), '{}') AS skills
            FROM agents a
            WHERE a.tenant_id = %s::uuid
              AND EXISTS (
                SELECT 1 FROM agent_skills s
                WHERE s.agent_id = a.id AND s.skill_id = %s
              )
            ORDER BY a.priority ASC, a.name ASC
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (self.tenant_id, skill)).fetchall()
        return [dict(r) for r in rows]

    def _get_agent(self, agent_id: str) -> dict[str, Any] | None:
        sql = """
            SELECT a.id::text AS agent_id,
                   a.agent_key,
                   a.name,
                   a.status,
                   a.priority,
                   COALESCE((
                     SELECT e.url FROM agent_endpoints e
                     WHERE e.agent_id = a.id AND e.is_primary = true
                     ORDER BY e.updated_at DESC LIMIT 1
                   ), '') AS endpoint,
                   COALESCE((
                     SELECT array_agg(s.skill_id ORDER BY s.skill_id)
                     FROM agent_skills s WHERE s.agent_id = a.id
                   ), '{}') AS skills
            FROM agents a
            WHERE a.tenant_id = %s::uuid
              AND (a.id::text = %s OR a.agent_key = %s)
            LIMIT 1
        """
        with connect(self.database_url) as conn:
            row = conn.execute(sql, (self.tenant_id, agent_id, agent_id)).fetchone()
        return dict(row) if row else None


def normalize_endpoint(url: str) -> str:
    """Map docker service hostnames to localhost when running agents on the host.

    Inside Compose set AOP_RUNTIME=docker so service DNS (search-agent, …) is kept.
    """
    runtime = os.getenv("AOP_RUNTIME", "").lower()
    if runtime in {"docker", "compose", "container"}:
        return url

    parsed = urlparse(url)
    host = parsed.hostname or ""
    mapped = {
        "search-agent": 8001,
        "rag-agent": 8002,
        "report-agent": 8003,
        "analysis-agent": 8004,
        "image-agent": 8005,
        "video-agent": 8006,
        "code-agent": 8007,
        "browser-agent": 8008,
        "ppt-agent": 8009,
    }
    if host in mapped:
        port = parsed.port or mapped[host]
        return f"http://127.0.0.1:{port}/"
    return url


def hitl_skills() -> set[str]:
    """Skills that pause for human approval after success (comma-separated env)."""
    raw = os.getenv("HITL_SKILLS", "report-generation,ppt-generation")
    if not raw or raw.strip().lower() in {"0", "false", "off", "none"}:
        return set()
    return {s.strip() for s in raw.split(",") if s.strip()}
