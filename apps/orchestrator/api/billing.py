"""Billing, quota, and egress HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app_context import ctx, require_admin, tenant_from_request
from billing.stripe_checkout import StripeCheckoutError
from billing.webhook import WebhookError

router = APIRouter(tags=["billing"])


class CreateInvoiceRequest(BaseModel):
    days: int = Field(default=30, ge=1, le=366)
    status: str = "draft"


class CheckoutRequest(BaseModel):
    dry_run: bool | None = None


class SimulatePaidRequest(BaseModel):
    stripe_session_id: str


class QuotaUpdateRequest(BaseModel):
    max_tasks_per_day: int | None = None
    max_agent_runs_per_day: int | None = None
    max_concurrent_tasks: int | None = None
    max_estimated_usd_per_month: float | None = None
    enabled: bool | None = None


class EgressUpdateRequest(BaseModel):
    mode: str | None = None
    patterns: str | None = None
    enabled: bool | None = None


@router.get("/v1/billing/usage")
def billing_usage(days: int = 30) -> dict[str, Any]:
    try:
        return ctx.tasks.billing_usage(days=days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "billing_error", "message": str(exc)}
        ) from exc


@router.get("/v1/billing/summary")
def billing_summary() -> dict[str, Any]:
    try:
        return ctx.tasks.billing_summary()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "billing_error", "message": str(exc)}
        ) from exc


@router.get("/v1/billing/invoice")
def billing_invoice_preview(days: int = 30) -> dict[str, Any]:
    try:
        return ctx.tasks.invoice_preview(days=days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "invoice_error", "message": str(exc)}
        ) from exc


@router.get("/v1/billing/invoice.md")
def billing_invoice_markdown(days: int = 30) -> Response:
    try:
        text = ctx.tasks.invoice_preview_markdown(days=days)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "invoice_error", "message": str(exc)}
        ) from exc
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'inline; filename="invoice-preview.md"'},
    )


@router.post("/v1/billing/invoices", status_code=201)
def billing_invoice_create(body: CreateInvoiceRequest) -> dict[str, Any]:
    try:
        return ctx.tasks.create_invoice(days=body.days, status=body.status)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "invoice_error", "message": str(exc)}
        ) from exc


@router.get("/v1/billing/invoices")
def billing_invoice_list(limit: int = 50) -> dict[str, Any]:
    try:
        return {"invoices": ctx.tasks.list_invoices(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "invoice_error", "message": str(exc)}
        ) from exc


@router.get("/v1/billing/invoices/{invoice_id}")
def billing_invoice_get(invoice_id: str) -> dict[str, Any]:
    row = ctx.tasks.get_invoice(invoice_id)
    if not row:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "invoice not found"}
        )
    return row


@router.post("/v1/billing/invoices/{invoice_id}/checkout", status_code=201)
def billing_invoice_checkout(
    invoice_id: str, body: CheckoutRequest | None = None
) -> dict[str, Any]:
    try:
        return ctx.tasks.create_checkout(
            invoice_id,
            dry_run=None if body is None else body.dry_run,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc
    except (ValueError, StripeCheckoutError) as exc:
        raise HTTPException(
            status_code=400, detail={"code": "checkout_error", "message": str(exc)}
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "checkout_error", "message": str(exc)}
        ) from exc


@router.get("/v1/billing/checkouts")
def billing_checkout_list(limit: int = 20) -> dict[str, Any]:
    try:
        return {"checkouts": ctx.tasks.list_checkouts(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "checkout_error", "message": str(exc)}
        ) from exc


@router.post("/v1/billing/webhooks/stripe")
async def billing_stripe_webhook(request: Request) -> dict[str, Any]:
    payload = await request.body()
    sig = request.headers.get("Stripe-Signature")
    try:
        return ctx.tasks.handle_stripe_webhook(payload, sig)
    except WebhookError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"code": "webhook_error", "message": str(exc)},
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "webhook_error", "message": str(exc)}
        ) from exc


@router.post("/v1/billing/checkouts/simulate-paid")
def billing_simulate_paid(body: SimulatePaidRequest, request: Request) -> dict[str, Any]:
    require_admin(request)
    try:
        return ctx.tasks.simulate_checkout_paid(body.stripe_session_id.strip())
    except PermissionError as exc:
        raise HTTPException(
            status_code=403, detail={"code": "forbidden", "message": str(exc)}
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "webhook_error", "message": str(exc)}
        ) from exc


@router.get("/v1/quotas")
def quotas_status() -> dict[str, Any]:
    try:
        return ctx.tasks.quota_status()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "quota_error", "message": str(exc)}
        ) from exc


@router.get("/v1/quotas/grants")
def quotas_grants(limit: int = 20) -> dict[str, Any]:
    try:
        return {"grants": ctx.tasks.list_quota_grants(limit=limit)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "quota_error", "message": str(exc)}
        ) from exc


@router.put("/v1/quotas")
def quotas_update(body: QuotaUpdateRequest, request: Request) -> dict[str, Any]:
    require_admin(request)
    ten = tenant_from_request(request)
    try:
        return ctx.tasks.update_quota(
            tenant_id=ten.tenant_id, **body.model_dump(exclude_none=True)
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "quota_error", "message": str(exc)}
        ) from exc


@router.get("/v1/egress")
def egress_get() -> dict[str, Any]:
    try:
        return ctx.tasks.egress_policy()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "egress_error", "message": str(exc)}
        ) from exc


@router.put("/v1/egress")
def egress_update(body: EgressUpdateRequest) -> dict[str, Any]:
    try:
        return ctx.tasks.update_egress(**body.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "validation_error", "message": str(exc)}
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "egress_error", "message": str(exc)}
        ) from exc


@router.get("/v1/egress/check")
def egress_check(url: str) -> dict[str, Any]:
    url = (url or "").strip()
    if not url:
        raise HTTPException(
            status_code=400,
            detail={"code": "validation_error", "message": "url query required"},
        )
    try:
        return ctx.tasks.check_egress(url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail={"code": "egress_error", "message": str(exc)}
        ) from exc
