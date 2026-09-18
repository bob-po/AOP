-- Phase 10: task evaluation
CREATE TABLE IF NOT EXISTS task_evaluations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  method        TEXT NOT NULL DEFAULT 'heuristic',
  score         REAL NOT NULL,
  grade         TEXT NOT NULL,
  dimensions    JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary       TEXT,
  details       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, method)
);

CREATE INDEX IF NOT EXISTS idx_task_evaluations_tenant_created
  ON task_evaluations(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_task_evaluations_score
  ON task_evaluations(score DESC);
