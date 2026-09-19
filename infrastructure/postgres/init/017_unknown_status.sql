-- Add unknown result state handling (P1-006)
-- This adds 'unknown' status for timeout/uncertain execution results

-- Update status constraint to include 'unknown'
ALTER TABLE a2a_requests DROP CONSTRAINT IF EXISTS a2a_requests_status_check;

ALTER TABLE a2a_requests ADD CONSTRAINT a2a_requests_status_check 
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'unknown'));

-- Comment for documentation
COMMENT ON COLUMN a2a_requests.status IS 'Request status: pending, running, completed, failed, cancelled, unknown (timeout/uncertain)';
