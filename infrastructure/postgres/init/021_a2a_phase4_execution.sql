-- Phase 4: durable execution plane — leases, ownership, outbox linkage, capacity queue.

-- ── Execution ownership / lease ───────────────────────────────────────────
ALTER TABLE a2a_execution_records
  ADD COLUMN IF NOT EXISTS owner_id TEXT,
  ADD COLUMN IF NOT EXISTS lease_until TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS sequence BIGINT NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_exec_lease
  ON a2a_execution_records (state, lease_until)
  WHERE lease_until IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_exec_stale_running
  ON a2a_execution_records (updated_at)
  WHERE state IN ('RUNNING', 'WAITING', 'RETRYING');

-- ── Outbox enrichment for execution events (reuse 014_outbox_events) ──────
ALTER TABLE outbox_events
  ADD COLUMN IF NOT EXISTS event_id TEXT,
  ADD COLUMN IF NOT EXISTS aggregate_type TEXT,
  ADD COLUMN IF NOT EXISTS aggregate_id TEXT,
  ADD COLUMN IF NOT EXISTS root_task_id TEXT,
  ADD COLUMN IF NOT EXISTS correlation_id TEXT,
  ADD COLUMN IF NOT EXISTS sequence BIGINT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_outbox_event_id
  ON outbox_events (event_id) WHERE event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_outbox_root ON outbox_events (root_task_id, sequence);
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate ON outbox_events (aggregate_type, aggregate_id);

-- ── Persist execution events (optional mirror of outbox for query API) ────
-- a2a_execution_events already exists from 020; ensure sequence column.
ALTER TABLE a2a_execution_events
  ADD COLUMN IF NOT EXISTS sequence BIGINT;

CREATE INDEX IF NOT EXISTS idx_exec_events_root_seq
  ON a2a_execution_events (root_task_id, sequence, id);

-- ── Capacity wait queue ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS a2a_capacity_queue (
  id               BIGSERIAL PRIMARY KEY,
  queue_key        TEXT NOT NULL,          -- usually agent_id
  task_id          TEXT NOT NULL,
  root_task_id     TEXT,
  correlation_id   TEXT,
  agent_id         TEXT NOT NULL,
  priority         INT NOT NULL DEFAULT 100,
  position         INT,
  state            TEXT NOT NULL DEFAULT 'WAITING',  -- WAITING | CLAIMED | CANCELLED | EXPIRED
  queued_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  timeout_at       TIMESTAMPTZ,
  claimed_at       TIMESTAMPTZ,
  metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_cap_queue_agent_state
  ON a2a_capacity_queue (agent_id, state, priority, queued_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cap_queue_task
  ON a2a_capacity_queue (task_id) WHERE state = 'WAITING';

-- ── Agent lifecycle persistence columns (table from 020) ──────────────────
ALTER TABLE a2a_agent_lifecycle
  ADD COLUMN IF NOT EXISTS heartbeat_timeout_s INT NOT NULL DEFAULT 60;

COMMENT ON COLUMN a2a_execution_records.lease_until IS 'Phase 4: ownership lease expiry; stale when now > lease_until';
COMMENT ON COLUMN a2a_execution_records.owner_id IS 'Phase 4: worker/orchestrator instance holding the lease';
COMMENT ON TABLE a2a_capacity_queue IS 'Phase 4: WAIT overflow when agent at max_concurrency';
