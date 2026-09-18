-- Phase 31: Stripe Checkout Session records

CREATE TABLE IF NOT EXISTS billing_checkout_sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  invoice_id        UUID REFERENCES billing_invoices(id) ON DELETE SET NULL,
  stripe_session_id TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'dry_run',
  url               TEXT,
  amount_total_cents INT,
  currency          TEXT NOT NULL DEFAULT 'usd',
  payload           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_billing_checkout_tenant_created
  ON billing_checkout_sessions (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_billing_checkout_invoice
  ON billing_checkout_sessions (invoice_id);
