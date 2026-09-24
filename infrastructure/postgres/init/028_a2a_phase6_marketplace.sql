-- Phase 6: Agent Manifest / Skill System / Marketplace persistence

-- ── Skills (catalog, versioned) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS a2a_skills (
  id              BIGSERIAL PRIMARY KEY,
  skill_key       TEXT NOT NULL,
  tenant_id       TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  name            TEXT NOT NULL,
  description     TEXT,
  status          TEXT NOT NULL DEFAULT 'PUBLISHED', -- DRAFT|PUBLISHED|DEPRECATED|REVOKED
  latest_version  TEXT,
  tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, skill_key)
);

CREATE TABLE IF NOT EXISTS a2a_skill_versions (
  id              BIGSERIAL PRIMARY KEY,
  skill_id        BIGINT NOT NULL REFERENCES a2a_skills(id) ON DELETE CASCADE,
  version         TEXT NOT NULL,
  description     TEXT,
  input_schema    JSONB NOT NULL DEFAULT '{}'::jsonb,
  output_schema   JSONB NOT NULL DEFAULT '{}'::jsonb,
  requirements    JSONB NOT NULL DEFAULT '{}'::jsonb,
  dependencies    JSONB NOT NULL DEFAULT '{}'::jsonb,
  status          TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE|INACTIVE|DEPRECATED|REVOKED
  checksum        TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (skill_id, version)
);

CREATE INDEX IF NOT EXISTS idx_skills_key ON a2a_skills (skill_key);
CREATE INDEX IF NOT EXISTS idx_skill_versions_status ON a2a_skill_versions (status);

-- ── Agent manifests (versioned, linked to registry agents) ────────────────
CREATE TABLE IF NOT EXISTS a2a_agent_manifests (
  id              BIGSERIAL PRIMARY KEY,
  agent_id        UUID REFERENCES agents(id) ON DELETE SET NULL,
  agent_key       TEXT NOT NULL,
  tenant_id       TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  version         TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'DRAFT', -- DRAFT|PUBLISHED|ACTIVE|INACTIVE|DEPRECATED|REVOKED
  manifest        JSONB NOT NULL,
  checksum        TEXT,
  publisher       TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, agent_key, version)
);

CREATE INDEX IF NOT EXISTS idx_agent_manifests_key ON a2a_agent_manifests (tenant_id, agent_key);
CREATE INDEX IF NOT EXISTS idx_agent_manifests_status ON a2a_agent_manifests (status);

-- ── Marketplace packages ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS a2a_marketplace_packages (
  id              BIGSERIAL PRIMARY KEY,
  package_id      TEXT NOT NULL,
  tenant_id       TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  kind            TEXT NOT NULL DEFAULT 'agent', -- agent | skill
  name            TEXT NOT NULL,
  description     TEXT,
  publisher       TEXT,
  status          TEXT NOT NULL DEFAULT 'DRAFT', -- DRAFT|PUBLISHED|DEPRECATED|REVOKED
  latest_version  TEXT,
  tags            JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, package_id)
);

CREATE TABLE IF NOT EXISTS a2a_marketplace_versions (
  id              BIGSERIAL PRIMARY KEY,
  package_ref     BIGINT NOT NULL REFERENCES a2a_marketplace_packages(id) ON DELETE CASCADE,
  version         TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'PUBLISHED',
  manifest        JSONB NOT NULL,
  checksum        TEXT,
  source_url      TEXT,
  changelog       TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (package_ref, version)
);

-- ── Installations (tenant-scoped) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS a2a_agent_installations (
  id              BIGSERIAL PRIMARY KEY,
  tenant_id       TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  package_id      TEXT NOT NULL,
  version         TEXT NOT NULL,
  agent_key       TEXT,
  agent_id        UUID,
  status          TEXT NOT NULL DEFAULT 'INSTALLING', -- INSTALLING|ACTIVATING|ACTIVE|DEACTIVATING|INACTIVE|FAILED
  endpoint        TEXT,
  sandbox         TEXT NOT NULL DEFAULT 'local_process',
  error           TEXT,
  metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_install_tenant ON a2a_agent_installations (tenant_id, status);

-- ── Dependencies ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS a2a_dependencies (
  id              BIGSERIAL PRIMARY KEY,
  tenant_id       TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  subject_kind    TEXT NOT NULL, -- agent | skill
  subject_key     TEXT NOT NULL,
  subject_version TEXT,
  dep_kind        TEXT NOT NULL, -- agent | skill | model | tool | runtime
  dep_key         TEXT NOT NULL,
  constraint_expr TEXT NOT NULL DEFAULT '*', -- e.g. >=1.2.0
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deps_subject ON a2a_dependencies (tenant_id, subject_kind, subject_key);

-- ── Permissions declared on manifests ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS a2a_agent_permissions (
  id              BIGSERIAL PRIMARY KEY,
  tenant_id       TEXT NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
  agent_key       TEXT NOT NULL,
  version         TEXT,
  permission      TEXT NOT NULL, -- network|filesystem|gpu|database|shell|external_api|other_agents
  granted         BOOLEAN NOT NULL DEFAULT false,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, agent_key, version, permission)
);

COMMENT ON TABLE a2a_skills IS 'Phase 6: structured Skill catalog';
COMMENT ON TABLE a2a_marketplace_packages IS 'Phase 6: Agent/Skill marketplace directory';
COMMENT ON TABLE a2a_agent_installations IS 'Phase 6: tenant install/activate state';
