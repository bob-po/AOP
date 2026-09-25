-- Node-level checkpoints (LangGraph-style durable snapshots per plan node).
-- Latest snapshot lives on task_nodes; attempt history in task_node_checkpoints.

ALTER TABLE task_nodes
  ADD COLUMN IF NOT EXISTS checkpoint_json JSONB,
  ADD COLUMN IF NOT EXISTS checkpoint_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS checkpoint_attempt INT;

COMMENT ON COLUMN task_nodes.checkpoint_json IS
  'Latest durable node snapshot (input summary / output refs / status / error)';
COMMENT ON COLUMN task_nodes.checkpoint_at IS
  'When checkpoint_json was last written';
COMMENT ON COLUMN task_nodes.checkpoint_attempt IS
  'Attempt number associated with checkpoint_json';

CREATE TABLE IF NOT EXISTS task_node_checkpoints (
  id            BIGSERIAL PRIMARY KEY,
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  node_id       UUID NOT NULL REFERENCES task_nodes(id) ON DELETE CASCADE,
  node_key      TEXT NOT NULL,
  attempt       INT NOT NULL DEFAULT 1,
  status        TEXT NOT NULL,
  snapshot_json JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_node_checkpoints_task
  ON task_node_checkpoints (task_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_node_checkpoints_node
  ON task_node_checkpoints (node_id, attempt DESC);

COMMENT ON TABLE task_node_checkpoints IS
  'Append-only history of plan-node checkpoints for replay / time-travel';
