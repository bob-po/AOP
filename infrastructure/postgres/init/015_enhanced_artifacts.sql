-- Enhanced artifact store for two-phase upload (P36.4)
-- This schema adds status, reference counting, and improved tracking

-- Add new columns to existing artifacts table if they don't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'artifacts' AND column_name = 'status'
    ) THEN
        ALTER TABLE artifacts ADD COLUMN status TEXT DEFAULT 'committed';
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'artifacts' AND column_name = 'reference_count'
    ) THEN
        ALTER TABLE artifacts ADD COLUMN reference_count INT DEFAULT 1;
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'artifacts' AND column_name = 'updated_at'
    ) THEN
        ALTER TABLE artifacts ADD COLUMN updated_at TIMESTAMPTZ DEFAULT now();
    END IF;
END $$;

-- Add constraint for status values
ALTER TABLE artifacts ADD CONSTRAINT artifacts_status_check 
  CHECK (status IN ('pending', 'committed', 'failed'));

-- Add constraint for reference count
ALTER TABLE artifacts ADD CONSTRAINT artifacts_reference_count_check 
  CHECK (reference_count >= 0);

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
