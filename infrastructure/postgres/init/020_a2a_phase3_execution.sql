-- Phase 3: execution records, execution events, agent lifecycle.

-- ── Execution records (SoT for task/delegation reliability) ───────────────
CREATE TABLE IF NOT EXISTS a2a_execution_records (
  id               BIGSERIAL PRIMARY KEY,
  task_id          TEXT NOT NULL,
  root_task_id     TEXT,
  correlation_id   TEXT,
  parent_task_id   TEXT,
  agent_id         TEXT,
  operation        TEXT NOT NULL DEFAULT 'execute',
  state            TEXT NOT NULL DEFAULT 'PENDING',
  attempt          INT  NOT NULL DEFAULT 0,
  max_retries      INT  NOT NULL DEFAULT 3,
  started_at       TIMESTAMPTZ,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at      TIMESTAMPTZ,
  duration_ms      BIGINT NOT NULL DEFAULT 0,
  error            TEXT,
  idempotency_key  TEXT,
  branch_lineage   JSONB NOT NULL DEFAULT '[]'::jsonb,
  visited_agents   JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
  ownership_token  TEXT,
  tenant_id        TEXT,
  UNIQUE (task_id, operation)
);

CREATE INDEX IF NOT EXISTS idx_exec_root ON a2a_execution_records(root_task_id);
CREATE INDEX IF NOT EXISTS idx_exec_corr ON a2a_execution_records(correlation_id);
CREATE INDEX IF NOT EXISTS idx_exec_state ON a2a_execution_records(state);
CREATE INDEX IF NOT EXISTS idx_exec_agent ON a2a_execution_records(agent_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_exec_idempotency
  ON a2a_execution_records(idempotency_key) WHERE idempotency_key IS NOT NULL;

-- ── Execution events (fact propagation, not SoT) ──────────────────────────
CREATE TABLE IF NOT EXISTS a2a_execution_events (
  id               BIGSERIAL PRIMARY KEY,
  event_id         TEXT NOT NULL UNIQUE,
  event_type       TEXT NOT NULL,
  timestamp        TIMESTAMPTZ NOT NULL DEFAULT now(),
  root_task_id     TEXT,
  correlation_id   TEXT,
  task_id          TEXT,
  agent_id         TEXT,
  parent_task_id   TEXT,
  payload          JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_exec_events_root ON a2a_execution_events(root_task_id, id);
CREATE INDEX IF NOT EXISTS idx_exec_events_task ON a2a_execution_events(task_id, id);
CREATE INDEX IF NOT EXISTS idx_exec_events_type ON a2a_execution_events(event_type, timestamp);

-- ── Agent lifecycle (OS-side; complements registry online/offline) ────────
CREATE TABLE IF NOT EXISTS a2a_agent_lifecycle (
  agent_id         TEXT PRIMARY KEY,
  state            TEXT NOT NULL DEFAULT 'REGISTERED',
  last_seen        TIMESTAMPTZ,
  active_tasks     INT NOT NULL DEFAULT 0,
  max_concurrency  INT NOT NULL DEFAULT 8,
  load             DOUBLE PRECISION NOT NULL DEFAULT 0,
  version          TEXT,
  capabilities     JSONB NOT NULL DEFAULT '{}'::jsonb,
  drain_started_at TIMESTAMPTZ,
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_agent_life_state ON a2a_agent_lifecycle(state);

-- Enrich runtime edges for live collaboration graph (Phase 3).
ALTER TABLE a2a_runtime_edges
  ADD COLUMN IF NOT EXISTS delegation_id TEXT,
  ADD COLUMN IF NOT EXISTS attempt INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS finished_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS duration_ms BIGINT,
  ADD COLUMN IF NOT EXISTS error TEXT,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_a2a_edges_delegation ON a2a_runtime_edges(delegation_id);

-- Governance policy extensions (Phase 3.14) — additive, defaults keep Phase 2 behavior.
ALTER TABLE a2a_governance_policies
  ADD COLUMN IF NOT EXISTS max_retries INT NOT NULL DEFAULT 3,
  ADD COLUMN IF NOT EXISTS task_timeout_s INT NOT NULL DEFAULT 300,
  ADD COLUMN IF NOT EXISTS delegation_timeout_s INT NOT NULL DEFAULT 120,
  ADD COLUMN IF NOT EXISTS agent_timeout_s INT NOT NULL DEFAULT 60,
  ADD COLUMN IF NOT EXISTS capacity_overflow TEXT NOT NULL DEFAULT 'reject',
  ADD COLUMN IF NOT EXISTS allowed_agents JSONB,
  ADD COLUMN IF NOT EXISTS denied_agents JSONB;

COMMENT ON TABLE a2a_execution_records IS 'Phase 3 SoT for task/delegation execution state';
COMMENT ON TABLE a2a_execution_events IS 'Phase 3 execution event stream (propagation, not SoT)';
COMMENT ON TABLE a2a_agent_lifecycle IS 'Phase 3 OS-side agent lifecycle (READY/BUSY/DRAINING/OFFLINE)';
