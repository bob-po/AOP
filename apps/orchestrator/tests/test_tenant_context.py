"""Phase 5.1 — TenantContext unit tests."""

from __future__ import annotations

import pytest

from scheduling.context import (
    DEFAULT_TENANT_ID,
    TenantContext,
    assert_same_tenant,
    get_tenant_context,
    reset_tenant_context,
    set_tenant_context,
)
from execution import ExecutionService


def test_tenant_context_from_headers():
    ctx = TenantContext.from_headers(
        {
            "X-Tenant-Id": "tenant-a",
            "X-User-Id": "u1",
            "X-Project-Id": "p1",
            "X-Priority": "high",
        }
    )
    assert ctx.tenant_id == "tenant-a"
    assert ctx.user_id == "u1"
    assert ctx.project_id == "p1"
    assert ctx.priority == "HIGH"


def test_tenant_isolation_blocks_cross_tenant():
    ctx = TenantContext(tenant_id="tenant-a")
    with pytest.raises(PermissionError):
        assert_same_tenant("tenant-b", ctx=ctx)


def test_tenant_isolation_allows_same():
    ctx = TenantContext(tenant_id="tenant-a")
    assert_same_tenant("tenant-a", ctx=ctx)


def test_contextvar_scopes_execution_create():
    svc = ExecutionService()
    token = set_tenant_context(TenantContext(tenant_id="tenant-z", user_id="uz"))
    try:
        assert get_tenant_context().tenant_id == "tenant-z"
        rec = svc.create(task_id="t-tenant", root_task_id="t-tenant")
        assert rec.tenant_id == "tenant-z"
        assert rec.user_id == "uz"
    finally:
        reset_tenant_context(token)
    assert get_tenant_context().tenant_id == DEFAULT_TENANT_ID


def test_default_tenant_constant():
    assert DEFAULT_TENANT_ID == "00000000-0000-0000-0000-000000000001"
