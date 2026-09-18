"""Phase 28: quota enforcement logic (mocked DB)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from quota import QuotaExceeded, QuotaService, quotas_enabled


def _conn_with_rows(*rows):
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    results = []
    for row in rows:
        m = MagicMock()
        if isinstance(row, list):
            m.fetchall = MagicMock(return_value=row)
            m.fetchone = MagicMock(return_value=row[0] if row else None)
        else:
            m.fetchone = MagicMock(return_value=row)
            m.fetchall = MagicMock(return_value=[row] if row else [])
        results.append(m)
    conn.execute.side_effect = results
    return conn


def test_quotas_enabled_env(monkeypatch):
    monkeypatch.setenv("TENANT_QUOTAS", "0")
    assert quotas_enabled() is False
    monkeypatch.setenv("TENANT_QUOTAS", "1")
    assert quotas_enabled() is True


def test_assert_can_create_skips_when_disabled(monkeypatch):
    monkeypatch.setenv("TENANT_QUOTAS", "0")
    svc = QuotaService(database_url="postgresql://invalid")
    out = svc.assert_can_create_task()
    assert out.get("skipped") is True


def test_assert_blocks_concurrent(monkeypatch):
    monkeypatch.setenv("TENANT_QUOTAS", "1")
    limits = {
        "tenant_id": "t",
        "max_tasks_per_day": 100,
        "max_agent_runs_per_day": 500,
        "max_concurrent_tasks": 2,
        "max_estimated_usd_per_month": 100.0,
        "enabled": True,
        "exists": True,
        "updated_at": None,
    }
    usage = {
        "tenant_id": "t",
        "tasks_today": 1,
        "agent_runs_today": 1,
        "concurrent_tasks": 2,
        "estimated_usd_30d": 1.0,
        "as_of": "now",
    }
    svc = QuotaService(database_url="postgresql://invalid")
    with (
        patch.object(svc, "get", return_value=limits),
        patch.object(svc, "usage_snapshot", return_value=usage),
    ):
        with pytest.raises(QuotaExceeded) as ei:
            svc.assert_can_create_task()
        assert ei.value.code == "quota_concurrent"


def test_assert_blocks_tasks_per_day(monkeypatch):
    monkeypatch.setenv("TENANT_QUOTAS", "1")
    limits = {
        "tenant_id": "t",
        "max_tasks_per_day": 3,
        "max_agent_runs_per_day": 500,
        "max_concurrent_tasks": 20,
        "max_estimated_usd_per_month": 100.0,
        "enabled": True,
        "exists": True,
        "updated_at": None,
    }
    usage = {
        "tenant_id": "t",
        "tasks_today": 3,
        "agent_runs_today": 0,
        "concurrent_tasks": 0,
        "estimated_usd_30d": 0.0,
        "as_of": "now",
    }
    svc = QuotaService(database_url="postgresql://invalid")
    with (
        patch.object(svc, "get", return_value=limits),
        patch.object(svc, "usage_snapshot", return_value=usage),
    ):
        with pytest.raises(QuotaExceeded, match="tasks today"):
            svc.assert_can_create_task()


def test_assert_ok_with_headroom(monkeypatch):
    monkeypatch.setenv("TENANT_QUOTAS", "1")
    limits = {
        "tenant_id": "t",
        "max_tasks_per_day": 10,
        "max_agent_runs_per_day": 50,
        "max_concurrent_tasks": 5,
        "max_estimated_usd_per_month": 100.0,
        "enabled": True,
        "exists": True,
        "updated_at": None,
    }
    usage = {
        "tenant_id": "t",
        "tasks_today": 1,
        "agent_runs_today": 2,
        "concurrent_tasks": 1,
        "estimated_usd_30d": 0.5,
        "as_of": "now",
    }
    svc = QuotaService(database_url="postgresql://invalid")
    with (
        patch.object(svc, "get", return_value=limits),
        patch.object(svc, "usage_snapshot", return_value=usage),
    ):
        snap = svc.assert_can_create_task()
        assert snap["headroom"]["tasks_today"] == 9
