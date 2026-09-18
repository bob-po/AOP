"""Stripe webhook verification + payment confirmation (Phase 32)."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any


class WebhookError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def webhook_secret() -> str:
    return os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()


def webhook_tolerance_seconds() -> int:
    return int(os.getenv("STRIPE_WEBHOOK_TOLERANCE", "300"))


def verify_stripe_signature(
    payload: bytes,
    sig_header: str | None,
    *,
    secret: str | None = None,
    tolerance: int | None = None,
) -> dict[str, Any]:
    """Verify Stripe-Signature header; return parsed JSON event.

    When STRIPE_WEBHOOK_SECRET is empty, accepts unsigned payloads only if
    STRIPE_WEBHOOK_ALLOW_UNSIGNED=1 (local/dev).
    """
    sec = (secret if secret is not None else webhook_secret()).strip()
    allow_unsigned = os.getenv("STRIPE_WEBHOOK_ALLOW_UNSIGNED", "0").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    if not sec:
        if not allow_unsigned:
            raise WebhookError(
                "STRIPE_WEBHOOK_SECRET not set (or enable STRIPE_WEBHOOK_ALLOW_UNSIGNED)",
                status_code=503,
            )
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise WebhookError(f"invalid json: {exc}") from exc

    if not sig_header:
        raise WebhookError("missing Stripe-Signature header")

    parts = {}
    for item in sig_header.split(","):
        item = item.strip()
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        parts.setdefault(k.strip(), []).append(v.strip())

    try:
        timestamp = int((parts.get("t") or [""])[0])
    except (TypeError, ValueError) as exc:
        raise WebhookError("invalid Stripe-Signature timestamp") from exc

    v1_sigs = parts.get("v1") or []
    if not v1_sigs:
        raise WebhookError("missing v1 signature")

    tol = webhook_tolerance_seconds() if tolerance is None else tolerance
    if abs(int(time.time()) - timestamp) > tol:
        raise WebhookError("webhook timestamp outside tolerance")

    signed = f"{timestamp}.".encode("utf-8") + payload
    expected = hmac.new(sec.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, cand) for cand in v1_sigs):
        raise WebhookError("invalid webhook signature", status_code=401)

    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise WebhookError(f"invalid json: {exc}") from exc


def sign_test_payload(payload: bytes, *, secret: str, timestamp: int | None = None) -> str:
    """Helper for unit tests — build Stripe-Signature header."""
    ts = int(time.time()) if timestamp is None else timestamp
    signed = f"{ts}.".encode("utf-8") + payload
    dig = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={dig}"


def extract_checkout_session(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return checkout.session object from supported event types."""
    etype = str(event.get("type") or "")
    if etype not in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.expired",
    }:
        return None
    obj = (event.get("data") or {}).get("object") or {}
    if not isinstance(obj, dict):
        return None
    return obj


def payment_outcome(event_type: str, session: dict[str, Any]) -> tuple[str, str]:
    """Return (checkout_status, invoice_status)."""
    if event_type == "checkout.session.expired":
        return "expired", "void"
    payment = str(session.get("payment_status") or "").lower()
    if event_type == "checkout.session.async_payment_succeeded":
        return "paid", "paid"
    if payment in {"paid", "no_payment_required"}:
        return "paid", "paid"
    # completed but not yet paid (e.g. bank transfer)
    return "complete", "issued"

