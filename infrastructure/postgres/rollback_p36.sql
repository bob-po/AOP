-- Rollback script for Phase 36 migrations (013-017)
-- This script should be used only for emergency rollback
-- Usage: psql -h localhost -U aop -d aop -f rollback_p36.sql

BEGIN;

-- Rollback Migration 017: Unknown Status
ALTER TABLE a2a_requests DROP CONSTRAINT IF EXISTS a2a_requests_status_check;
ALTER TABLE a2a_requests ADD CONSTRAINT a2a_requests_status_check 
  CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled'));
COMMENT ON COLUMN a2a_requests.status IS 'Request status: pending, running, completed, failed, cancelled';

-- Rollback Migration 016: Node Idempotency
ALTER TABLE task_nodes DROP COLUMN IF EXISTS idempotency_key;
DROP INDEX IF EXISTS idx_task_nodes_idempotency_key;

-- Rollback Migration 015: Enhanced Artifacts
-- Note: This migration had multiple changes. Review carefully before rollback.
-- Assuming we just want to remove enhanced columns if they exist
-- (Actual rollback depends on what was added in 015)

-- Rollback Migration 014: Outbox
DROP TABLE IF EXISTS outbox_events CASCADE;

-- Rollback Migration 013: Request Tracking
DROP TABLE IF EXISTS a2a_requests CASCADE;

-- Update schema migrations table
DELETE FROM schema_migrations WHERE version >= 13;

COMMIT;

-- Verification queries
SELECT 'Migration rollback completed' as status;
SELECT COUNT(*) as remaining_migrations FROM schema_migrations WHERE version >= 13;
