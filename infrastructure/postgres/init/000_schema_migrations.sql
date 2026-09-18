-- Phase 18: schema migration tracking (applied by migrate.py / docker init)
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,
  checksum    TEXT NOT NULL DEFAULT '',
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
