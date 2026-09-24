-- Phase 5.3: per-execution cost records (linked to Execution Record).

CREATE TABLE IF NOT EXISTS a2a_cost_records (
  id               BIGSERIAL PRIMARY KEY,
  task_id          TEXT NOT NULL,
  root_task_id     TEXT,
  correlation_id   TEXT,
  execution_op     TEXT NOT NULL DEFAULT 'execute',
  agent_id         TEXT,
  tenant_id        TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  model            TEXT,
  input_tokens     BIGINT NOT NULL DEFAULT 0,
  output_tokens    BIGINT NOT NULL DEFAULT 0,
  gpu_seconds      DOUBLE PRECISION NOT NULL DEFAULT 0,
  cpu_seconds      DOUBLE PRECISION NOT NULL DEFAULT 0,
  wall_time_ms     BIGINT NOT NULL DEFAULT 0,
  network_bytes    BIGINT NOT NULL DEFAULT 0,
  storage_bytes    BIGINT NOT NULL DEFAULT 0,
  estimated_cost   NUMERIC(18, 8) NOT NULL DEFAULT 0,
  currency         TEXT NOT NULL DEFAULT 'USD',
  attempt          INT NOT NULL DEFAULT 0,
  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One cost row per (task, operation, attempt) — retries get independent costs
CREATE UNIQUE INDEX IF NOT EXISTS uq_cost_task_op_attempt
  ON a2a_cost_records (task_id, execution_op, attempt);

CREATE INDEX IF NOT EXISTS idx_cost_root ON a2a_cost_records (root_task_id);
CREATE INDEX IF NOT EXISTS idx_cost_tenant ON a2a_cost_records (tenant_id, created_at);
CREATE INDEX IF NOT EXISTS idx_cost_agent ON a2a_cost_records (agent_id);

COMMENT ON TABLE a2a_cost_records IS 'Phase 5: Execution→Cost 1:1 (per attempt); aggregate by root_task_id';
