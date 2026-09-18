"""Phase 32: Stripe webhook signature + payment outcome."""

from __future__ import annotations

import json
import os
import time

import pytest

from billing.webhook import (
    WebhookError,
    extract_checkout_session,
    payment_outcome,
    sign_test_payload,
    verify_stripe_signature,
)


def test_verify_signature_ok(monkeypatch):
    secret = "whsec_test_secret"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    monkeypatch.delenv("STRIPE_WEBHOOK_ALLOW_UNSIGNED", raising=False)
    body = json.dumps(
        {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {"id": "cs_1"}}}
    ).encode()
    sig = sign_test_payload(body, secret=secret)
    event = verify_stripe_signature(body, sig)
    assert event["id"] == "evt_1"


def test_verify_signature_rejects_bad(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test_secret")
    body = b'{"id":"evt_1","type":"x"}'
    ts = int(time.time())
    with pytest.raises(WebhookError, match="invalid webhook signature"):
        verify_stripe_signature(body, f"t={ts},v1=deadbeef")


def test_verify_unsigned_when_allowed(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("STRIPE_WEBHOOK_ALLOW_UNSIGNED", "1")
    body = b'{"id":"evt_u","type":"checkout.session.completed"}'
    event = verify_stripe_signature(body, None)
    assert event["id"] == "evt_u"


def test_verify_unsigned_blocked_without_flag(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("STRIPE_WEBHOOK_ALLOW_UNSIGNED", raising=False)
    with pytest.raises(WebhookError, match="STRIPE_WEBHOOK_SECRET"):
        verify_stripe_signature(b"{}", None)


def test_timestamp_tolerance(monkeypatch):
    secret = "whsec_x"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    body = b'{"id":"evt_old"}'
    old = int(time.time()) - 10_000
    sig = sign_test_payload(body, secret=secret, timestamp=old)
    with pytest.raises(WebhookError, match="tolerance"):
        verify_stripe_signature(body, sig)


def test_extract_and_outcome():
    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_x", "payment_status": "paid"}},
    }
    session = extract_checkout_session(event)
    assert session["id"] == "cs_x"
    assert payment_outcome("checkout.session.completed", session) == ("paid", "paid")
    assert payment_outcome(
        "checkout.session.expired", {"payment_status": "unpaid"}
    ) == ("expired", "void")
    assert payment_outcome(
        "checkout.session.completed", {"payment_status": "unpaid"}
    ) == ("complete", "issued")


def test_ignored_event_type():
    assert extract_checkout_session({"type": "customer.created", "data": {}}) is None
