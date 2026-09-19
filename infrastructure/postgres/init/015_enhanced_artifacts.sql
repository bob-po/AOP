-- Enhanced artifact store for two-phase upload (P36.4)
-- This schema adds status, reference counting, and improved tracking

-- Create artifacts table if it doesn't exist (for P36.4)
CREATE TABLE IF NOT EXISTS artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  node_key TEXT NOT NULL,
  name TEXT NOT NULL,
  content_type TEXT,
  size BIGINT,
  uri TEXT NOT NULL,
  status TEXT DEFAULT 'committed',
  reference_count INT DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- Add index for pending artifacts cleanup
CREATE INDEX IF NOT EXISTS idx_artifacts_status_created ON artifacts(status, created_at);

-- Add index for reference count queries
CREATE INDEX IF NOT EXISTS idx_artifacts_reference_count ON artifacts(reference_count);

-- Add index for task queries
CREATE INDEX IF NOT EXISTS idx_artifacts_task_status ON artifacts(task_id, status);

-- Comment for documentation
COMMENT ON TABLE artifacts IS 'Artifact storage with two-phase upload support';
COMMENT ON COLUMN artifacts.status IS 'Artifact status: pending (uploading), committed (confirmed), failed (upload failed)';
COMMENT ON COLUMN artifacts.reference_count IS 'Number of references to this artifact (for garbage collection)';
COMMENT ON COLUMN artifacts.updated_at IS 'Last update timestamp';

-- Add index for pending artifacts cleanup
CREATE INDEX IF NOT EXISTS idx_artifacts_status_created ON artifacts(status, created_at);

-- Add index for reference count queries
CREATE INDEX IF NOT EXISTS idx_artifacts_reference_count ON artifacts(reference_count);

-- Add index for task queries
CREATE INDEX IF NOT EXISTS idx_artifacts_task_status ON artifacts(task_id, status);

-- Comment for documentation
COMMENT ON COLUMN artifacts.status IS 'Artifact status: pending (uploading), committed (confirmed), failed (upload failed)';
COMMENT ON COLUMN artifacts.reference_count IS 'Number of references to this artifact (for garbage collection)';
COMMENT ON COLUMN artifacts.updated_at IS 'Last update timestamp';
