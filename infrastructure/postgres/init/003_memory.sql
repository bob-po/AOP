-- Phase 12: task-scoped working memory
CREATE TABLE IF NOT EXISTS task_memories (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  memory_key    TEXT NOT NULL,
  content       TEXT NOT NULL,
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, memory_key)
);

CREATE INDEX IF NOT EXISTS idx_task_memories_tenant_updated
  ON task_memories(tenant_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_memories_task
  ON task_memories(task_id, memory_key);
