"""Phase 5 — TenantContext + request-scoped helpers (no second auth system)."""

from __future__ import annotations

import contextvars
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

_current: contextvars.ContextVar[Optional["TenantContext"]] = contextvars.ContextVar(
    "a2a_tenant_context", default=None
)


@dataclass
class TenantContext:
    """Unified tenant context for Task / Execution / Delegation / Scheduling."""

    tenant_id: str = DEFAULT_TENANT_ID
    user_id: Optional[str] = None
    project_id: Optional[str] = None
    priority: str = "NORMAL"  # CRITICAL | HIGH | NORMAL | LOW
    quota: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_headers(
        cls,
        headers: dict[str, str] | None = None,
        *,
        default_tenant: str = DEFAULT_TENANT_ID,
    ) -> "TenantContext":
        h = {str(k).lower(): v for k, v in (headers or {}).items()}
        tenant = (
            h.get("x-tenant-id")
            or h.get("x-aop-tenant-id")
            or default_tenant
        )
        return cls(
            tenant_id=str(tenant).strip() or default_tenant,
            user_id=h.get("x-user-id") or h.get("x-aop-user-id"),
            project_id=h.get("x-project-id") or h.get("x-aop-project-id"),
            priority=(h.get("x-priority") or "NORMAL").upper(),
        )

    @classmethod
    def from_mapping(cls, data: dict[str, Any] | None) -> "TenantContext":
        data = data or {}
        return cls(
            tenant_id=str(data.get("tenant_id") or DEFAULT_TENANT_ID),
            user_id=data.get("user_id"),
            project_id=data.get("project_id"),
            priority=str(data.get("priority") or "NORMAL").upper(),
            quota=dict(data.get("quota") or {}),
            budget=dict(data.get("budget") or {}),
            policy=dict(data.get("policy") or {}),
        )


def get_tenant_context() -> TenantContext:
    ctx = _current.get()
    return ctx if ctx is not None else TenantContext()


def set_tenant_context(ctx: TenantContext | None) -> contextvars.Token:
    return _current.set(ctx)


def reset_tenant_context(token: contextvars.Token) -> None:
    _current.reset(token)


def assert_same_tenant(
    resource_tenant_id: str | None,
    *,
    ctx: TenantContext | None = None,
    allow_default_cross_read: bool = True,
) -> None:
    """Raise PermissionError if caller tenant cannot access resource.

    Default-tenant resources remain readable by default-tenant callers (legacy).
    Non-default tenants cannot read other tenants' data.
    """
    ctx = ctx or get_tenant_context()
    res = resource_tenant_id or DEFAULT_TENANT_ID
    caller = ctx.tenant_id or DEFAULT_TENANT_ID
    if caller == res:
        return
    if allow_default_cross_read and caller == DEFAULT_TENANT_ID and res == DEFAULT_TENANT_ID:
        return
    if caller != res:
        raise PermissionError(
            f"tenant isolation: caller={caller} cannot access resource tenant={res}"
        )


__all__ = [
    "DEFAULT_TENANT_ID",
    "TenantContext",
    "get_tenant_context",
    "set_tenant_context",
    "reset_tenant_context",
    "assert_same_tenant",
]
