-- Phase 34: per-tenant egress (outbound URL) policy

CREATE TABLE IF NOT EXISTS tenant_egress_policies (
  tenant_id     UUID PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
  -- open | allowlist | denylist
  mode          TEXT NOT NULL DEFAULT 'open',
  -- comma-separated host patterns: example.com, *.wikipedia.org
  patterns      TEXT NOT NULL DEFAULT '',
  enabled       BOOLEAN NOT NULL DEFAULT true,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT tenant_egress_mode_chk CHECK (mode IN ('open', 'allowlist', 'denylist'))
);

INSERT INTO tenant_egress_policies (tenant_id, mode, patterns, enabled)
VALUES ('00000000-0000-0000-0000-000000000001', 'open', '', true)
ON CONFLICT (tenant_id) DO NOTHING;
