-- Phase 5.2 / 5.10: budget + extended resource quotas (additive; wraps tenant_quotas).

CREATE TABLE IF NOT EXISTS a2a_budgets (
  id               BIGSERIAL PRIMARY KEY,
  tenant_id        TEXT NOT NULL,
  project_id       TEXT,
  scope            TEXT NOT NULL DEFAULT 'tenant', -- tenant | project | task | day | month
  scope_key        TEXT NOT NULL DEFAULT '',       -- task_id or YYYY-MM-DD / YYYY-MM
  currency         TEXT NOT NULL DEFAULT 'USD',
  limit_amount     NUMERIC(18, 8) NOT NULL,
  spent_amount     NUMERIC(18, 8) NOT NULL DEFAULT 0,
  soft_limit       BOOLEAN NOT NULL DEFAULT false,
  enabled          BOOLEAN NOT NULL DEFAULT true,
  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_budget_scope
  ON a2a_budgets (tenant_id, scope, scope_key);

CREATE INDEX IF NOT EXISTS idx_budget_tenant ON a2a_budgets (tenant_id);

-- Optional resource envelope (cpu/gpu/mem) — complements tenant_quotas concurrency/USD
CREATE TABLE IF NOT EXISTS a2a_resource_quotas (
  tenant_id        TEXT NOT NULL,
  project_id       TEXT NOT NULL DEFAULT '',
  cpu              DOUBLE PRECISION NOT NULL DEFAULT 32,
  memory_mb        BIGINT NOT NULL DEFAULT 65536,
  gpu              INT NOT NULL DEFAULT 0,
  max_concurrency  INT NOT NULL DEFAULT 20,
  max_queue_depth  INT NOT NULL DEFAULT 100,
  tokens_per_day   BIGINT NOT NULL DEFAULT 1000000,
  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, project_id)
);

INSERT INTO a2a_resource_quotas (tenant_id, project_id)
VALUES ('00000000-0000-0000-0000-000000000001', '')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE a2a_budgets IS 'Phase 5: per-tenant/project/task/day/month spend limits';
COMMENT ON TABLE a2a_resource_quotas IS 'Phase 5: OS resource envelope; enforcement via QuotaService + Governance';
