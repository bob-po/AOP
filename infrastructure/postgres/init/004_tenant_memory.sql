-- Phase 20: tenant-scoped long-term memory (cross-task)
CREATE TABLE IF NOT EXISTS tenant_memories (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  memory_key    TEXT NOT NULL,
  title         TEXT,
  content       TEXT NOT NULL,
  source_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_tenant_memories_tenant_updated
  ON tenant_memories(tenant_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_tenant_memories_source_task
  ON tenant_memories(source_task_id)
  WHERE source_task_id IS NOT NULL;
