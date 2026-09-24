-- Phase 5.11: optional scheduling decision audit (not a second Router).

CREATE TABLE IF NOT EXISTS a2a_scheduling_decisions (
  id               BIGSERIAL PRIMARY KEY,
  tenant_id        TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  root_task_id     TEXT,
  correlation_id   TEXT,
  skill            TEXT,
  selected_agent_id TEXT,
  candidates       JSONB NOT NULL DEFAULT '[]'::jsonb,
  excluded         JSONB NOT NULL DEFAULT '[]'::jsonb,
  scores           JSONB NOT NULL DEFAULT '{}'::jsonb,
  estimated_cost   NUMERIC(18, 8) NOT NULL DEFAULT 0,
  estimated_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
  policy           JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sched_dec_tenant
  ON a2a_scheduling_decisions (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sched_dec_root
  ON a2a_scheduling_decisions (root_task_id);

COMMENT ON TABLE a2a_scheduling_decisions IS 'Phase 5: audit trail for IntelligentScheduler selections';
