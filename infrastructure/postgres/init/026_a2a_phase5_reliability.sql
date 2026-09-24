-- Phase 5.7: agent reliability rollups (derived from execution records; not SoT).

CREATE TABLE IF NOT EXISTS a2a_agent_reliability (
  agent_id           TEXT PRIMARY KEY,
  tenant_id          TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  success_rate       DOUBLE PRECISION NOT NULL DEFAULT 0,
  failure_rate       DOUBLE PRECISION NOT NULL DEFAULT 0,
  timeout_rate       DOUBLE PRECISION NOT NULL DEFAULT 0,
  retry_rate         DOUBLE PRECISION NOT NULL DEFAULT 0,
  average_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
  p95_latency_ms     DOUBLE PRECISION NOT NULL DEFAULT 0,
  p99_latency_ms     DOUBLE PRECISION NOT NULL DEFAULT 0,
  recent_failures    INT NOT NULL DEFAULT 0,
  availability       DOUBLE PRECISION NOT NULL DEFAULT 1,
  sample_size        INT NOT NULL DEFAULT 0,
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata           JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_rel_tenant
  ON a2a_agent_reliability (tenant_id);

COMMENT ON TABLE a2a_agent_reliability IS 'Phase 5: scheduling input rollup; Execution Record remains SoT';
