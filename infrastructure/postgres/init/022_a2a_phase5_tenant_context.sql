-- Phase 5.1: tenant context columns on A2A execution plane (compatible backfill).

-- Execution records
ALTER TABLE a2a_execution_records
  ADD COLUMN IF NOT EXISTS tenant_id TEXT,
  ADD COLUMN IF NOT EXISTS user_id TEXT,
  ADD COLUMN IF NOT EXISTS project_id TEXT;

UPDATE a2a_execution_records
   SET tenant_id = '00000000-0000-0000-0000-000000000001'
 WHERE tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_exec_tenant_root
  ON a2a_execution_records (tenant_id, root_task_id);
CREATE INDEX IF NOT EXISTS idx_exec_tenant_state
  ON a2a_execution_records (tenant_id, state);

-- Execution events (if table exists from 020)
ALTER TABLE a2a_execution_events
  ADD COLUMN IF NOT EXISTS tenant_id TEXT;

UPDATE a2a_execution_events
   SET tenant_id = '00000000-0000-0000-0000-000000000001'
 WHERE tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_exec_events_tenant_root
  ON a2a_execution_events (tenant_id, root_task_id);

-- Capacity queue
ALTER TABLE a2a_capacity_queue
  ADD COLUMN IF NOT EXISTS tenant_id TEXT;

UPDATE a2a_capacity_queue
   SET tenant_id = '00000000-0000-0000-0000-000000000001'
 WHERE tenant_id IS NULL;

-- Runtime edges already have tenant_id from 018; ensure index for isolation queries
CREATE INDEX IF NOT EXISTS idx_runtime_edges_tenant_root
  ON a2a_runtime_edges (tenant_id, root_task_id);

COMMENT ON COLUMN a2a_execution_records.tenant_id IS 'Phase 5: tenant isolation key; default tenant for legacy rows';
