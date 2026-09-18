-- Phase 32: Stripe webhook idempotency + paid timestamps

ALTER TABLE billing_checkout_sessions
  ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS payment_status TEXT;

ALTER TABLE billing_invoices
  ADD COLUMN IF NOT EXISTS paid_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS billing_webhook_events (
  id              BIGSERIAL PRIMARY KEY,
  stripe_event_id TEXT NOT NULL UNIQUE,
  event_type      TEXT NOT NULL,
  checkout_session_id TEXT,
  invoice_id      UUID REFERENCES billing_invoices(id) ON DELETE SET NULL,
  payload         JSONB NOT NULL DEFAULT '{}'::jsonb,
  processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_webhook_processed
  ON billing_webhook_events (processed_at DESC);
