-- A2A Request Tracking for P36.1 Idempotency
-- This schema enables exactly-once execution by tracking A2A requests

CREATE TABLE IF NOT EXISTS a2a_requests (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  idempotency_key TEXT NOT NULL UNIQUE,
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  node_id UUID REFERENCES task_nodes(id) ON DELETE CASCADE,
  agent_id UUID REFERENCES agents(id),
  status TEXT NOT NULL DEFAULT 'pending',
  request_json JSONB,
  response_json JSONB,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_a2a_requests_idempotency ON a2a_requests(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_a2a_requests_task ON a2a_requests(task_id);
CREATE INDEX IF NOT EXISTS idx_a2a_requests_node ON a2a_requests(node_id);
CREATE INDEX IF NOT EXISTS idx_a2a_requests_agent ON a2a_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_a2a_requests_status ON a2a_requests(status, created_at);

-- Status values: pending, running, completed, failed, cancelled
ALTER TABLE a2a_requests ADD CONSTRAINT a2a_requests_status_check 
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));

-- Comment for documentation
COMMENT ON TABLE a2a_requests IS 'Tracks A2A requests for idempotency and exactly-once execution';
COMMENT ON COLUMN a2a_requests.idempotency_key IS 'Unique key to prevent duplicate A2A executions';
COMMENT ON COLUMN a2a_requests.status IS 'Request status: pending, running, completed, failed, cancelled';
