-- Phase 28: per-tenant usage quotas

CREATE TABLE IF NOT EXISTS tenant_quotas (
  tenant_id                 UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  max_tasks_per_day         INT NOT NULL DEFAULT 100,
  max_agent_runs_per_day    INT NOT NULL DEFAULT 500,
  max_concurrent_tasks      INT NOT NULL DEFAULT 20,
  max_estimated_usd_per_month NUMERIC(12, 4) NOT NULL DEFAULT 100.0000,
  enabled                   BOOLEAN NOT NULL DEFAULT true,
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO tenant_quotas (tenant_id)
VALUES ('00000000-0000-0000-0000-000000000001')
ON CONFLICT (tenant_id) DO NOTHING;
