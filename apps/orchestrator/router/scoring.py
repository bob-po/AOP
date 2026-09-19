"""Configurable Scoring Engine for Router v3.

This module provides policy-based scoring with configurable weights,
maintaining backward compatibility with existing Router v2 implementation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

ONLINE_STATUSES = frozenset({"online", "running"})


@dataclass
class ScoringWeights:
    """Configurable scoring weights for agent selection."""

    availability: float = 0.10
    priority: float = 0.25
    latency: float = 0.30
    success_rate: float = 0.35
    cost: float = 0.0

    def validate(self) -> None:
        """Validate that weights sum to approximately 1.0."""
        total = sum([
            self.availability,
            self.priority,
            self.latency,
            self.success_rate,
            self.cost,
        ])
        if not (0.99 <= total <= 1.01):  # Allow small floating point errors
            raise ValueError(f"Scoring weights must sum to 1.0, got {total:.4f}")

    @classmethod
    def from_env(cls) -> ScoringWeights:
        """Create ScoringWeights from environment variables."""
        return cls(
            availability=float(os.getenv("ROUTER_WEIGHT_AVAILABILITY", "0.10")),
            priority=float(os.getenv("ROUTER_WEIGHT_PRIORITY", "0.25")),
            latency=float(os.getenv("ROUTER_WEIGHT_LATENCY", "0.30")),
            success_rate=float(os.getenv("ROUTER_WEIGHT_SUCCESS_RATE", "0.35")),
            cost=float(os.getenv("ROUTER_WEIGHT_COST", "0.0")),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoringWeights:
        """Create ScoringWeights from dictionary."""
        return cls(
            availability=float(data.get("availability", 0.10)),
            priority=float(data.get("priority", 0.25)),
            latency=float(data.get("latency", 0.30)),
            success_rate=float(data.get("success_rate", 0.35)),
            cost=float(data.get("cost", 0.0)),
        )

    def to_dict(self) -> dict[str, float]:
        """Convert to dictionary."""
        return {
            "availability": self.availability,
            "priority": self.priority,
            "latency": self.latency,
            "success_rate": self.success_rate,
            "cost": self.cost,
        }


@dataclass
class ScoringPolicy:
    """Complete scoring policy configuration."""

    weights: ScoringWeights = field(default_factory=ScoringWeights)
    cold_start_success_rate: float = 0.85
    cold_start_latency_score: float = 0.75
    latency_cutoff_ms: int = 5000
    priority_max: int = 200
    enable_cost_scoring: bool = False

    def __post_init__(self) -> None:
        self.weights.validate()

    @classmethod
    def default(cls) -> ScoringPolicy:
        """Create default scoring policy (matches Router v2 hardcoded values)."""
        return cls(
            weights=ScoringWeights(
                availability=0.10,
                priority=0.25,
                latency=0.30,
                success_rate=0.35,
                cost=0.0,
            ),
            cold_start_success_rate=0.85,
            cold_start_latency_score=0.75,
            latency_cutoff_ms=5000,
            priority_max=200,
            enable_cost_scoring=False,
        )

    @classmethod
    def from_env(cls) -> ScoringPolicy:
        """Create ScoringPolicy from environment variables."""
        weights = ScoringWeights.from_env()
        return cls(
            weights=weights,
            cold_start_success_rate=float(os.getenv("ROUTER_COLD_START_SUCCESS_RATE", "0.85")),
            cold_start_latency_score=float(os.getenv("ROUTER_COLD_START_LATENCY_SCORE", "0.75")),
            latency_cutoff_ms=int(os.getenv("ROUTER_LATENCY_CUTOFF_MS", "5000")),
            priority_max=int(os.getenv("ROUTER_PRIORITY_MAX", "200")),
            enable_cost_scoring=os.getenv("ROUTER_ENABLE_COST_SCORING", "false").lower() in {"true", "1", "yes"},
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScoringPolicy:
        """Create ScoringPolicy from dictionary."""
        weights_data = data.get("weights", {})
        return cls(
            weights=ScoringWeights.from_dict(weights_data),
            cold_start_success_rate=float(data.get("cold_start_success_rate", 0.85)),
            cold_start_latency_score=float(data.get("cold_start_latency_score", 0.75)),
            latency_cutoff_ms=int(data.get("latency_cutoff_ms", 5000)),
            priority_max=int(data.get("priority_max", 200)),
            enable_cost_scoring=bool(data.get("enable_cost_scoring", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "weights": self.weights.to_dict(),
            "cold_start_success_rate": self.cold_start_success_rate,
            "cold_start_latency_score": self.cold_start_latency_score,
            "latency_cutoff_ms": self.latency_cutoff_ms,
            "priority_max": self.priority_max,
            "enable_cost_scoring": self.enable_cost_scoring,
        }


class ScoringEngine:
    """Configurable scoring engine for agent selection."""

    def __init__(self, policy: ScoringPolicy | None = None):
        self.policy = policy or ScoringPolicy.default()

    def score_candidate(
        self,
        candidate: dict[str, Any],
        metrics: dict[str, Any],
    ) -> dict[str, float]:
        """Score a single candidate using policy weights.

        Args:
            candidate: Agent candidate dictionary
            metrics: Agent metrics from agent_runs

        Returns:
            Dictionary with individual scores and total score
        """
        scores = {
            "availability": self._score_availability(candidate),
            "priority": self._score_priority(candidate),
            "latency": self._score_latency(metrics),
            "success_rate": self._score_success_rate(metrics),
            "cost": self._score_cost(candidate, metrics) if self.policy.enable_cost_scoring else 0.0,
        }

        total = sum(
            scores[k] * getattr(self.policy.weights, k)
            for k in scores
        )

        scores["total"] = round(total, 4)
        scores["availability"] = round(scores["availability"], 4)
        scores["priority"] = round(scores["priority"], 4)
        scores["latency"] = round(scores["latency"], 4)
        scores["success_rate"] = round(scores["success_rate"], 4)
        scores["cost"] = round(scores["cost"], 4)

        return scores

    def _score_availability(self, candidate: dict[str, Any]) -> float:
        """Score based on availability (online status).

        Args:
            candidate: Agent candidate dictionary

        Returns:
            Availability score (0.0 to 1.0)
        """
        status = candidate.get("status", "")
        return 1.0 if status in ONLINE_STATUSES else 0.0

    def _score_priority(self, candidate: dict[str, Any]) -> float:
        """Score based on priority (1 best, priority_max worst).

        Args:
            candidate: Agent candidate dictionary

        Returns:
            Priority score (0.0 to 1.0)
        """
        priority = int(candidate.get("priority") or 100)
        return max(0.0, min(1.0, 1.0 - ((priority - 1) / (self.policy.priority_max - 1))))

    def _score_latency(self, metrics: dict[str, Any]) -> float:
        """Score based on latency (lower is better).

        Args:
            metrics: Agent metrics from agent_runs

        Returns:
            Latency score (0.0 to 1.0)
        """
        req = int(metrics.get("request_count") or 0)
        avg_lat = float(metrics.get("avg_latency_ms") or 0.0)

        if req == 0:
            return self.policy.cold_start_latency_score

        return max(0.0, min(1.0, 1.0 - (avg_lat / self.policy.latency_cutoff_ms)))

    def _score_success_rate(self, metrics: dict[str, Any]) -> float:
        """Score based on success rate (higher is better).

        Args:
            metrics: Agent metrics from agent_runs

        Returns:
            Success rate score (0.0 to 1.0)
        """
        req = int(metrics.get("request_count") or 0)
        ok = int(metrics.get("success_count") or 0)

        if req == 0:
            return self.policy.cold_start_success_rate

        return ok / req

    def _score_cost(self, candidate: dict[str, Any], metrics: dict[str, Any]) -> float:
        """Score based on cost (lower is better).

        Args:
            candidate: Agent candidate dictionary
            metrics: Agent metrics from agent_runs

        Returns:
            Cost score (0.0 to 1.0)
        """
        # TODO: Implement cost scoring when cost data is available
        # Currently returns 0.0 (neutral)
        return 0.0


__all__ = [
    "ScoringWeights",
    "ScoringPolicy",
    "ScoringEngine",
]
