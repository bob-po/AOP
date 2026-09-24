-- Phase 2.2: OS-level governance, quota and budget for autonomous A2A collaboration.
--
-- The OS Runtime is the trusted authority: Agents cannot raise their own limits.
-- Counters live in the database (not in-process) so they are correct across the
-- multiple processes that make up a real Agent network.

-- ── Governance policies ────────────────────────────────────────────────────
-- A policy can be global (tenant_id NULL, agent_id NULL), tenant-scoped, or
-- agent-scoped. Resolution order at runtime: agent > tenant > global default.
CREATE TABLE IF NOT EXISTS a2a_governance_policies (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name             TEXT NOT NULL,
  tenant_id        UUID,
  agent_id         TEXT,                 -- logical agent_key; NULL = applies to all
  max_delegation_depth   INT  NOT NULL DEFAULT 5,
  max_calls_per_root     INT  NOT NULL DEFAULT 50,
  max_agent_visits       INT  NOT NULL DEFAULT 3,   -- allow A->B->A, block runaway
  max_agent_concurrency  INT  NOT NULL DEFAULT 8,
  max_tenant_concurrency INT  NOT NULL DEFAULT 64,
  max_task_lifetime_s    INT  NOT NULL DEFAULT 900,  -- 15 min default deadline
  max_budget_units_root  NUMERIC(18,4) NOT NULL DEFAULT 1000,
  max_budget_units_call  NUMERIC(18,4) NOT NULL DEFAULT 100,
  enabled          BOOLEAN NOT NULL DEFAULT true,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_governance_policy_scope
  ON a2a_governance_policies (COALESCE(tenant_id, '00000000-0000-0000-0000-000000000000'),
                              COALESCE(agent_id, '*'));
CREATE INDEX IF NOT EXISTS idx_governance_policy_tenant ON a2a_governance_policies (tenant_id);

-- Global default policy (seeded once).
INSERT INTO a2a_governance_policies (name, tenant_id, agent_id)
SELECT 'global-default', NULL, NULL
WHERE NOT EXISTS (
  SELECT 1 FROM a2a_governance_policies WHERE tenant_id IS NULL AND agent_id IS NULL
);

-- ── Budget / usage accounting (per root task) ──────────────────────────────
-- units are an extensible abstract "cost" meter. Until a unified token/money
-- meter exists, one delegation call = 1 unit; token estimates may be added by a
-- caller and MUST be flagged estimated=true. We never fabricate provider costs.
CREATE TABLE IF NOT EXISTS a2a_budget_usage (
  root_task_id     TEXT PRIMARY KEY,
  correlation_id   TEXT,
  tenant_id        UUID,
  calls            INT NOT NULL DEFAULT 0,
  units_used       NUMERIC(18,4) NOT NULL DEFAULT 0,
  units_are_estimated BOOLEAN NOT NULL DEFAULT false,
  first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_budget_usage_tenant ON a2a_budget_usage (tenant_id, updated_at);

-- ── Governance denials (audit) ─────────────────────────────────────────────
-- Every rejection is recorded with a stable code and full lineage so it can be
-- queried from Task/Audit and never silently dropped.
CREATE TABLE IF NOT EXISTS a2a_governance_denials (
  id               BIGSERIAL PRIMARY KEY,
  root_task_id     TEXT,
  correlation_id   TEXT,
  caller_agent_id  TEXT,
  target_agent_id  TEXT,
  tenant_id        UUID,
  code             TEXT NOT NULL,        -- RECURSION_LIMIT_EXCEEDED / CALL_LIMIT_EXCEEDED /
                                         -- CYCLE_DETECTED / BUDGET_EXCEEDED / QUOTA_EXCEEDED /
                                         -- CONCURRENCY_LIMIT_EXCEEDED / DEADLINE_EXCEEDED /
                                         -- NO_AGENT_AVAILABLE / POLICY_DISABLED
  reason           TEXT,
  depth            INT NOT NULL DEFAULT 0,
  requested_units  NUMERIC(18,4),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gov_denials_root ON a2a_governance_denials (root_task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_gov_denials_code ON a2a_governance_denials (code, created_at);
CREATE INDEX IF NOT EXISTS idx_gov_denials_tenant ON a2a_governance_denials (tenant_id, created_at);

COMMENT ON TABLE a2a_governance_policies IS 'OS-authoritative governance limits; Agents cannot self-raise them.';
COMMENT ON TABLE a2a_budget_usage IS 'Per-root-task cumulative call/budget accounting (DB-backed, cross-process safe).';
COMMENT ON TABLE a2a_governance_denials IS 'Audit log of governance rejections with stable codes and lineage.';
