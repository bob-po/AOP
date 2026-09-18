-- Phase 33: quota grants after successful Stripe payment

ALTER TABLE tenant_quotas
  ADD COLUMN IF NOT EXISTS plan_tier TEXT NOT NULL DEFAULT 'free',
  ADD COLUMN IF NOT EXISTS last_paid_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS tenant_quota_grants (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  invoice_id      UUID REFERENCES billing_invoices(id) ON DELETE SET NULL,
  stripe_event_id TEXT,
  amount_usd      NUMERIC(14, 6) NOT NULL DEFAULT 0,
  before_limits   JSONB NOT NULL DEFAULT '{}'::jsonb,
  after_limits    JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_quota_grants_tenant_created
  ON tenant_quota_grants (tenant_id, created_at DESC);
