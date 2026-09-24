-- Phase 5.4: optional capability mirror (Agent Card remains source; this aids queries).

CREATE TABLE IF NOT EXISTS a2a_agent_capabilities (
  agent_id       TEXT PRIMARY KEY,
  tenant_id      TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  skills         JSONB NOT NULL DEFAULT '[]'::jsonb,
  input_types    JSONB NOT NULL DEFAULT '["text"]'::jsonb,
  output_types   JSONB NOT NULL DEFAULT '["text"]'::jsonb,
  models         JSONB NOT NULL DEFAULT '[]'::jsonb,
  tools          JSONB NOT NULL DEFAULT '[]'::jsonb,
  modalities     JSONB NOT NULL DEFAULT '["text"]'::jsonb,
  streaming      BOOLEAN NOT NULL DEFAULT false,
  browsing       BOOLEAN NOT NULL DEFAULT false,
  execution      BOOLEAN NOT NULL DEFAULT false,
  gpu            BOOLEAN NOT NULL DEFAULT false,
  max_context    INT NOT NULL DEFAULT 0,
  version        TEXT NOT NULL DEFAULT '1',
  raw            JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_caps_tenant
  ON a2a_agent_capabilities (tenant_id);

COMMENT ON TABLE a2a_agent_capabilities IS 'Phase 5: capability index for matching; registry card remains authoritative';
