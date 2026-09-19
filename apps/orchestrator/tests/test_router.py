"""Router scoring and endpoint normalization (no database)."""

from __future__ import annotations

import os
from unittest.mock import patch

from router import AgentRouter, hitl_skills, normalize_endpoint
from router.scoring import ScoringWeights, ScoringPolicy, ScoringEngine


def test_normalize_endpoint_maps_docker_hostnames():
    assert normalize_endpoint("http://search-agent:8001/") == "http://127.0.0.1:8001/"
    assert normalize_endpoint("http://rag-agent:8002/a2a") == "http://127.0.0.1:8002/"
    assert normalize_endpoint("http://example.com:9000/") == "http://example.com:9000/"


def test_score_prefers_high_success_low_latency():
    router = AgentRouter(database_url="postgresql://invalid/invalid")
    router.smart = True
    good = router._score(
        {"priority": 50, "status": "online"},
        {"request_count": 20, "success_count": 19, "avg_latency_ms": 100},
    )
    bad = router._score(
        {"priority": 50, "status": "online"},
        {"request_count": 20, "success_count": 5, "avg_latency_ms": 4000},
    )
    assert good["total"] > bad["total"]


def test_score_cold_start_prior_when_no_samples():
    router = AgentRouter(database_url="postgresql://invalid/invalid")
    router.smart = True
    cold = router._score({"priority": 100, "status": "online"}, {})
    assert cold["success_rate"] == 0.85
    assert 0.0 < cold["total"] <= 1.0


def test_smart_off_uses_priority_only():
    router = AgentRouter(database_url="postgresql://invalid/invalid")
    router.smart = False
    breakdown = router._score(
        {"priority": 1, "status": "online"},
        {"request_count": 100, "success_count": 1, "avg_latency_ms": 5000},
    )
    assert breakdown["total"] == breakdown["priority"]


def test_hitl_skills_parsing():
    with patch.dict(os.environ, {"HITL_SKILLS": "report-generation,text-to-image"}):
        assert hitl_skills() == {"report-generation", "text-to-image"}
    with patch.dict(os.environ, {"HITL_SKILLS": "off"}):
        assert hitl_skills() == set()


def test_scoring_weights_validate():
    # Valid weights
    weights = ScoringWeights(
        availability=0.10,
        priority=0.25,
        latency=0.30,
        success_rate=0.35,
        cost=0.0,
    )
    weights.validate()  # Should not raise

    # Invalid weights (sum != 1.0)
    invalid_weights = ScoringWeights(
        availability=0.80,
        priority=0.50,
        latency=0.0,
        success_rate=0.0,
        cost=0.0,
    )
    try:
        invalid_weights.validate()
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "must sum to 1.0" in str(exc)


def test_scoring_weights_from_env():
    with patch.dict(
        os.environ,
        {
            "ROUTER_WEIGHT_AVAILABILITY": "0.15",
            "ROUTER_WEIGHT_PRIORITY": "0.20",
            "ROUTER_WEIGHT_LATENCY": "0.25",
            "ROUTER_WEIGHT_SUCCESS_RATE": "0.30",
            "ROUTER_WEIGHT_COST": "0.10",
        },
    ):
        weights = ScoringWeights.from_env()
        assert weights.availability == 0.15
        assert weights.priority == 0.20
        assert weights.latency == 0.25
        assert weights.success_rate == 0.30
        assert weights.cost == 0.10


def test_scoring_policy_default():
    policy = ScoringPolicy.default()
    assert policy.weights.availability == 0.10
    assert policy.weights.priority == 0.25
    assert policy.weights.latency == 0.30
    assert policy.weights.success_rate == 0.35
    assert policy.weights.cost == 0.0
    assert policy.cold_start_success_rate == 0.85
    assert policy.cold_start_latency_score == 0.75
    assert policy.latency_cutoff_ms == 5000
    assert policy.priority_max == 200
    assert policy.enable_cost_scoring is False


def test_scoring_engine_uses_policy():
    policy = ScoringPolicy(
        weights=ScoringWeights(
            availability=0.20,
            priority=0.20,
            latency=0.20,
            success_rate=0.40,
            cost=0.0,
        )
    )
    engine = ScoringEngine(policy)

    candidate = {"priority": 50, "status": "online"}
    metrics = {"request_count": 20, "success_count": 19, "avg_latency_ms": 100}

    scores = engine.score_candidate(candidate, metrics)

    # Verify custom weights are used
    assert scores["availability"] == 1.0
    assert scores["success_rate"] == 0.95
    assert scores["latency"] > 0.9  # Low latency = high score
    assert 0.0 <= scores["total"] <= 1.0
    
    # Verify total uses custom weights
    expected_total = (
        scores["availability"] * 0.20
        + scores["priority"] * 0.20
        + scores["latency"] * 0.20
        + scores["success_rate"] * 0.40
    )
    assert abs(scores["total"] - expected_total) < 0.01


def test_scoring_engine_cost_disabled():
    policy = ScoringPolicy(enable_cost_scoring=False)
    engine = ScoringEngine(policy)

    candidate = {"priority": 50, "status": "online"}
    metrics = {"request_count": 20, "success_count": 19, "avg_latency_ms": 100}

    scores = engine.score_candidate(candidate, metrics)

    # Cost should be 0.0 when disabled
    assert scores["cost"] == 0.0


def test_scoring_engine_backward_compatibility():
    # Test that default policy matches Router v2 hardcoded weights
    policy = ScoringPolicy.default()
    engine = ScoringEngine(policy)

    candidate = {"priority": 50, "status": "online"}
    metrics = {"request_count": 20, "success_count": 19, "avg_latency_ms": 100}

    scores = engine.score_candidate(candidate, metrics)

    # Verify scores match Router v2 behavior
    assert scores["availability"] == 1.0
    assert scores["success_rate"] == 0.95
    assert scores["latency"] > 0.9  # 100ms is very good
    assert scores["priority"] > 0.5  # Priority 50 out of 200
    
    # Total should match Router v2 formula
    expected_total = (
        scores["availability"] * 0.10
        + scores["success_rate"] * 0.35
        + scores["latency"] * 0.30
        + scores["priority"] * 0.25
    )
    assert abs(scores["total"] - expected_total) < 0.01
