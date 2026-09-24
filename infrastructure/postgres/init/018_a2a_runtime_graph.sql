-- A2A OS: runtime execution graph (Agent-to-Agent call edges).
--
-- This table records the *runtime* call graph produced when Agents autonomously
-- discover and invoke one another. It is explicitly NOT a predefined workflow
-- DAG: edges are appended as calls actually happen, keyed by task lineage
-- (root_task_id / parent_task_id / correlation_id) so a whole collaboration can
-- be reconstructed after the fact.

CREATE TABLE IF NOT EXISTS a2a_runtime_edges (
  id              BIGSERIAL PRIMARY KEY,
  root_task_id    TEXT,
  parent_task_id  TEXT,
  task_id         TEXT,
  correlation_id  TEXT,
  caller_agent_id TEXT NOT NULL,
  target_agent_id TEXT NOT NULL,
  skill           TEXT,
  depth           INTEGER NOT NULL DEFAULT 0,
  status          TEXT NOT NULL DEFAULT 'submitted',
  tenant_id       TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_a2a_edges_root ON a2a_runtime_edges(root_task_id);
CREATE INDEX IF NOT EXISTS idx_a2a_edges_correlation ON a2a_runtime_edges(correlation_id);
CREATE INDEX IF NOT EXISTS idx_a2a_edges_parent ON a2a_runtime_edges(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_a2a_edges_created ON a2a_runtime_edges(created_at);

COMMENT ON TABLE a2a_runtime_edges IS 'Runtime Agent-to-Agent execution graph edges (not a predefined DAG)';
