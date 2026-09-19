-- Add idempotency_key to task_nodes for stable retry tracking (P36.1 fix)
-- This enables stable idempotency keys across retries

ALTER TABLE task_nodes ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

-- Create index for fast lookup
CREATE INDEX IF NOT EXISTS idx_task_nodes_idempotency_key ON task_nodes(idempotency_key);

-- Comment for documentation
COMMENT ON COLUMN task_nodes.idempotency_key IS 'Stable idempotency key for this node execution, reused across retries';
