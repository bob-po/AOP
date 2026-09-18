"""Phase 33: payment → quota boost helpers."""

from __future__ import annotations

from quota import compute_boosted_limits, next_plan_tier, payment_boost_enabled


def test_compute_boosted_limits():
    cur = {
        "max_tasks_per_day": 100,
        "max_agent_runs_per_day": 500,
        "max_concurrent_tasks": 20,
        "max_estimated_usd_per_month": 100.0,
    }
    boost = {
        "tasks_per_day_add": 50,
        "runs_per_day_add": 200,
        "concurrent_add": 5,
        "usd_month_add_factor": 10.0,
        "usd_month_add_min": 50.0,
    }
    out = compute_boosted_limits(cur, amount_usd=2.0, boost=boost)
    assert out["max_tasks_per_day"] == 150
    assert out["max_agent_runs_per_day"] == 700
    assert out["max_concurrent_tasks"] == 25
    # max(50, 2*10) = 50
    assert out["max_estimated_usd_per_month"] == 150.0


def test_compute_boost_uses_factor_when_larger():
    cur = {"max_tasks_per_day": 0, "max_agent_runs_per_day": 0, "max_concurrent_tasks": 0, "max_estimated_usd_per_month": 0}
    boost = {
        "tasks_per_day_add": 0,
        "runs_per_day_add": 0,
        "concurrent_add": 0,
        "usd_month_add_factor": 10.0,
        "usd_month_add_min": 50.0,
    }
    out = compute_boosted_limits(cur, amount_usd=20.0, boost=boost)
    assert out["max_estimated_usd_per_month"] == 200.0


def test_next_plan_tier():
    assert next_plan_tier("free", 0) == "free"
    assert next_plan_tier("free", 1) == "starter"
    assert next_plan_tier("starter", 2) == "starter"
    assert next_plan_tier("starter", 3) == "pro"
    assert next_plan_tier("pro", 1) == "pro"


def test_payment_boost_env(monkeypatch):
    monkeypatch.setenv("QUOTA_PAYMENT_BOOST", "0")
    assert payment_boost_enabled() is False
    monkeypatch.setenv("QUOTA_PAYMENT_BOOST", "1")
    assert payment_boost_enabled() is True
