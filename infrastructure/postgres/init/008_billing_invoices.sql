-- Phase 30: persisted billing invoice snapshots

CREATE TABLE IF NOT EXISTS billing_invoices (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  invoice_number TEXT NOT NULL,
  currency      TEXT NOT NULL DEFAULT 'USD',
  window_days   INT NOT NULL,
  period_start  TIMESTAMPTZ NOT NULL,
  period_end    TIMESTAMPTZ NOT NULL,
  subtotal_usd  NUMERIC(14, 6) NOT NULL DEFAULT 0,
  total_usd     NUMERIC(14, 6) NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'draft',
  line_items    JSONB NOT NULL DEFAULT '[]'::jsonb,
  usage_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, invoice_number)
);

CREATE INDEX IF NOT EXISTS idx_billing_invoices_tenant_created
  ON billing_invoices (tenant_id, created_at DESC);
