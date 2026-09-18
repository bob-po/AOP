"""Router scoring and endpoint normalization (no database)."""

from __future__ import annotations

import os
from unittest.mock import patch

from router import AgentRouter, hitl_skills, normalize_endpoint


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
