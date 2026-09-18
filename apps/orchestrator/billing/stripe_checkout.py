"""Stripe Checkout Session helper (Phase 31).

Creates a real Checkout Session when STRIPE_SECRET_KEY is set;
otherwise returns a dry-run payload matching Stripe shapes.
"""

from __future__ import annotations

import os
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx


class StripeCheckoutError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def stripe_secret() -> str:
    return os.getenv("STRIPE_SECRET_KEY", "").strip()


def stripe_configured() -> bool:
    return bool(stripe_secret())


def success_url() -> str:
    return os.getenv(
        "STRIPE_SUCCESS_URL",
        "http://127.0.0.1:3000/settings?checkout=success",
    )


def cancel_url() -> str:
    return os.getenv(
        "STRIPE_CANCEL_URL",
        "http://127.0.0.1:3000/settings?checkout=cancel",
    )


def build_checkout_params(invoice: dict[str, Any]) -> dict[str, Any]:
    """Form fields for Stripe Checkout Session create."""
    currency = str(invoice.get("currency") or "USD").lower()
    line_items = (invoice.get("stripe") or {}).get("line_items") or []
    if not line_items:
        # Rebuild from invoice line_items
        line_items = []
        for item in invoice.get("line_items") or []:
            unit = float(item.get("unit_amount_usd") or 0)
            qty = int(item.get("quantity") or 0)
            if unit <= 0 or qty <= 0:
                continue
            line_items.append(
                {
                    "price_data": {
                        "currency": currency,
                        "product_data": {
                            "name": str(item.get("description") or "AOP usage")[:120]
                        },
                        "unit_amount": int(round(unit * 100)),
                    },
                    "quantity": qty,
                }
            )

    params: dict[str, Any] = {
        "mode": "payment",
        "success_url": success_url(),
        "cancel_url": cancel_url(),
        "client_reference_id": str(
            invoice.get("id") or invoice.get("invoice_number") or ""
        )[:200],
        "metadata[invoice_number]": str(invoice.get("invoice_number") or ""),
        "metadata[tenant_id]": str(invoice.get("tenant_id") or ""),
    }
    for i, li in enumerate(line_items):
        pd = li.get("price_data") or {}
        prod = pd.get("product_data") or {}
        params[f"line_items[{i}][price_data][currency]"] = pd.get("currency") or currency
        params[f"line_items[{i}][price_data][product_data][name]"] = prod.get("name") or "AOP"
        params[f"line_items[{i}][price_data][unit_amount]"] = int(pd.get("unit_amount") or 0)
        params[f"line_items[{i}][quantity]"] = int(li.get("quantity") or 1)
    return params


def create_checkout_session(
    invoice: dict[str, Any],
    *,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    """Return checkout session dict. dry_run forced True if no secret."""
    params = build_checkout_params(invoice)
    has_lines = any(k.startswith("line_items[") for k in params)
    if not has_lines:
        raise StripeCheckoutError("invoice has no billable line items")

    force_dry = dry_run if dry_run is not None else not stripe_configured()
    if force_dry or not stripe_configured():
        sid = f"cs_test_dry_{uuid.uuid4().hex[:16]}"
        return {
            "id": sid,
            "object": "checkout.session",
            "mode": "payment",
            "status": "dry_run",
            "url": f"https://checkout.stripe.com/c/pay/{sid}#dry_run",
            "dry_run": True,
            "success_url": params["success_url"],
            "cancel_url": params["cancel_url"],
            "client_reference_id": params.get("client_reference_id"),
            "amount_total": int(round(float(invoice.get("total_usd") or 0) * 100)),
            "currency": str(invoice.get("currency") or "usd").lower(),
            "note": "Dry-run — set STRIPE_SECRET_KEY to create a live Checkout Session.",
        }

    # Live Stripe API (form-urlencoded)
    try:
        resp = httpx.post(
            "https://api.stripe.com/v1/checkout/sessions",
            content=urlencode(params),
            headers={
                "Authorization": f"Bearer {stripe_secret()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        raise StripeCheckoutError(f"stripe request failed: {exc}") from exc

    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        msg = (data.get("error") or {}).get("message") or resp.text[:300]
        raise StripeCheckoutError(msg, status_code=resp.status_code, body=data)

    return {
        "id": data.get("id"),
        "object": data.get("object", "checkout.session"),
        "mode": data.get("mode"),
        "status": data.get("status") or "open",
        "url": data.get("url"),
        "dry_run": False,
        "success_url": data.get("success_url"),
        "cancel_url": data.get("cancel_url"),
        "client_reference_id": data.get("client_reference_id"),
        "amount_total": data.get("amount_total"),
        "currency": data.get("currency"),
        "raw": {"id": data.get("id"), "payment_status": data.get("payment_status")},
    }
