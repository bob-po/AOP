-- Outbox pattern for distributed transaction coordination (P36.2)
-- This schema enables atomic coordination between PostgreSQL and Redis operations

CREATE TABLE IF NOT EXISTS outbox_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  payload JSONB NOT NULL,
  target_stream TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at TIMESTAMPTZ
);

-- Indexes for efficient processing
CREATE INDEX IF NOT EXISTS idx_outbox_status_created ON outbox_events(status, created_at);
CREATE INDEX IF NOT EXISTS idx_outbox_type ON outbox_events(event_type);
CREATE INDEX IF NOT EXISTS idx_outbox_target ON outbox_events(target_stream);

-- Status values: pending, processing, processed, failed
ALTER TABLE outbox_events ADD CONSTRAINT outbox_events_status_check 
  CHECK (status IN ('pending', 'processing', 'processed', 'failed'));

-- Comment for documentation
COMMENT ON TABLE outbox_events IS 'Outbox events for reliable message delivery to Redis streams';
COMMENT ON COLUMN outbox_events.event_type IS 'Type of event (e.g., job_enqueue, task_completed)';
COMMENT ON COLUMN outbox_events.target_stream IS 'Target Redis stream (e.g., a2a.execution.queue)';
COMMENT ON COLUMN outbox_events.status IS 'Event status: pending, processing, processed, failed';
COMMENT ON COLUMN outbox_events.attempts IS 'Number of processing attempts';
