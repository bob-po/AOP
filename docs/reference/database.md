# 数据库设计（PostgreSQL）

> 配套文档：[技术方案主文档](./A2A-Agent-调度平台-v1.0-技术方案.md)  
> Schema 源：`infrastructure/postgres/init/*.sql`（`000`–`012`）  
> 迁移工具：`python infrastructure/postgres/migrate.py`（跟踪表 `schema_migrations`）  
> Phase 18 起：禁止 Orchestrator 运行时 DDL；Memory / Evaluation 仅读写已迁移表  
> Phase 20：`tenant_memories` 跨任务长期记忆（TF-IDF 检索）  
> Phase 28：`tenant_quotas` 租户用量限额  
> Phase 30：`billing_invoices` 发票快照  
> Phase 31：`billing_checkout_sessions` Stripe Checkout  
> Phase 32：`billing_webhook_events` + paid_at

## 1. ER 关系总览

```
Tenant
 │
 ├──────────────┐
 ▼              ▼
Agent          User / api_keys
 │
 ├── agent_versions
 ├── agent_skills
 ├── agent_endpoints
 ├── agent_runs          ← 智能路由评分数据源
 └── agent_metrics       ← 预留窗口聚合（可选）

Task
 │
 ├── task_nodes  ──► Agent (assigned)
 ├── task_dependencies
 ├── task_events
 ├── task_evaluations    ← Phase 10
 └── task_memories       ← Phase 12
 └── tenant_memories     ← Phase 20（跨任务）
 └── tenant_quotas       ← Phase 28
 └── billing_invoices    ← Phase 30
 └── billing_checkout_sessions ← Phase 31
 └── billing_webhook_events ← Phase 32
 └── tenant_quota_grants  ← Phase 33
 └── tenant_egress_policies ← Phase 34

Workflow
 └── workflow_versions

audit_logs
```

## 2. 核心表定义

### 2.1 租户与用户

```sql
CREATE TABLE tenants (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'active', -- active | suspended
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  email         TEXT NOT NULL,
  display_name  TEXT,
  role          TEXT NOT NULL DEFAULT 'member', -- owner | admin | member
  status        TEXT NOT NULL DEFAULT 'active',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, email)
);
```

默认租户：`00000000-0000-0000-0000-000000000001`（`default`）。

### 2.2 Agent Registry

```sql
CREATE TABLE agents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID REFERENCES tenants(id),
  agent_key     TEXT NOT NULL,
  name          TEXT NOT NULL,
  description   TEXT,
  protocol      TEXT NOT NULL DEFAULT 'A2A',
  status        TEXT NOT NULL DEFAULT 'created',
  -- created | registered | verified | online | running | offline | degraded | disabled
  current_version TEXT,
  card_json     JSONB,
  priority      INT NOT NULL DEFAULT 100,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, agent_key)
);

CREATE TABLE agent_versions ( ... );
CREATE TABLE agent_skills (
  ...
  skill_id      TEXT NOT NULL,
  UNIQUE (agent_id, skill_id)
);
CREATE INDEX idx_agent_skills_skill_id ON agent_skills(skill_id);

CREATE TABLE agent_endpoints (
  ...
  url           TEXT NOT NULL,
  auth_type     TEXT NOT NULL DEFAULT 'none',
  is_primary    BOOLEAN NOT NULL DEFAULT true
);

-- 预留：窗口聚合指标（当前路由主要读 agent_runs 实时聚合）
CREATE TABLE agent_metrics ( ... );
```

### 2.3 Task / DAG

```sql
CREATE TABLE tasks (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  user_id       UUID REFERENCES users(id),
  title         TEXT,
  input_json    JSONB NOT NULL,
  status        TEXT NOT NULL DEFAULT 'created',
  -- created | planning | planned | ready | running
  -- | waiting_for_user   ← HITL（Phase 11）
  -- | completed | failed | cancelled
  progress      INT NOT NULL DEFAULT 0,
  plan_json     JSONB,          -- DAG；节点可含 requires_approval
  result_json   JSONB,
  error_message TEXT,
  workflow_id   UUID,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ
);

CREATE TABLE task_nodes (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  node_key      TEXT NOT NULL,
  skill         TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'pending',
  -- pending | ready | running | success | waiting_for_user
  -- | failed | retrying | skipped | cancelled
  assigned_agent_id UUID REFERENCES agents(id),
  input_json    JSONB,
  output_json   JSONB,
  attempt       INT NOT NULL DEFAULT 0,
  max_retry     INT NOT NULL DEFAULT 3,
  error_message TEXT,
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, node_key)
);

CREATE TABLE task_dependencies ( ... );
CREATE TABLE task_events ( ... );  -- 只追加；支撑 Trace / HITL / Evaluation 事件
```

**长任务回收：** Worker 扫描 `status='running'` 且 `started_at` 超过 `NODE_STALE_SECONDS`（默认 900）的节点，标记 retrying 并重新入队，或超 `max_retry` 则失败。

### 2.4 Agent Run（智能路由数据源）

```sql
CREATE TABLE agent_runs (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  node_id       UUID NOT NULL REFERENCES task_nodes(id) ON DELETE CASCADE,
  agent_id      UUID NOT NULL REFERENCES agents(id),
  a2a_task_id   TEXT,
  status        TEXT NOT NULL DEFAULT 'running',  -- success | failed | ...
  request_json  JSONB,
  response_json JSONB,
  latency_ms    INT,
  cost_usd      NUMERIC,
  error_message TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at   TIMESTAMPTZ
);

CREATE INDEX idx_agent_runs_agent ON agent_runs(agent_id, created_at DESC);
CREATE INDEX idx_agent_runs_task ON agent_runs(task_id);
```

Router v2 在窗口（`ROUTER_METRICS_HOURS`，默认 24h）内按 success_rate / latency / priority 打分。

### 2.5 Workflow

```sql
CREATE TABLE workflows ( ... status: draft | published | archived ... );
CREATE TABLE workflow_versions (
  workflow_id   UUID NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
  version       TEXT NOT NULL,
  dag_json      JSONB NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT false,
  UNIQUE (workflow_id, version)
);
```

### 2.6 Evaluation（Phase 10 · `002_evaluation.sql`）

```sql
CREATE TABLE IF NOT EXISTS task_evaluations (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  method        TEXT NOT NULL DEFAULT 'heuristic',
  score         REAL NOT NULL,
  grade         TEXT NOT NULL,          -- A..F
  dimensions    JSONB NOT NULL DEFAULT '{}'::jsonb,
  summary       TEXT,
  details       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, method)
);

CREATE INDEX idx_task_evaluations_tenant_created
  ON task_evaluations(tenant_id, created_at DESC);
CREATE INDEX idx_task_evaluations_score ON task_evaluations(score DESC);
```

启发式维度：completeness · reliability · artifacts · latency。

### 2.7 Memory（Phase 12 · `003_memory.sql`）

```sql
CREATE TABLE IF NOT EXISTS task_memories (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  task_id       UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  memory_key    TEXT NOT NULL,           -- goal | node:{key} | 自定义
  content       TEXT NOT NULL,
  metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (task_id, memory_key)
);

CREATE INDEX idx_task_memories_tenant_updated
  ON task_memories(tenant_id, updated_at DESC);
CREATE INDEX idx_task_memories_task ON task_memories(task_id, memory_key);
```

### 2.8 API Key / Audit

```sql
CREATE TABLE api_keys (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id     UUID NOT NULL REFERENCES tenants(id),
  name          TEXT NOT NULL,
  key_prefix    TEXT NOT NULL,
  key_hash      TEXT NOT NULL,
  scopes        TEXT[] NOT NULL DEFAULT '{}',
  status        TEXT NOT NULL DEFAULT 'active',
  expires_at    TIMESTAMPTZ,
  last_used_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs ( ... );  -- 预留
```

## 3. 设计约定

| 约定 | 说明 |
|------|------|
| UUID | 业务主键使用 UUID |
| `tenant_id` | 默认单租户，字段已全覆盖 |
| JSONB | Card / Plan / Artifact / dimensions / metadata |
| 状态字段 | TEXT + 应用层枚举 |
| Skill 索引 | `agent_skills.skill_id` + Redis `agent:skill:{id}` |
| 事件表 | `task_events` 只追加 |
| 幂等建表 | Evaluation / Memory 支持 `CREATE IF NOT EXISTS` |

## 4. 初始化

```bash
docker compose -f deployments/docker-compose.yml up -d postgres
# 首次建库：自动执行 infrastructure/postgres/init/*.sql
# 已有库 / 补 checksum：python infrastructure/postgres/migrate.py
```

```sql
INSERT INTO tenants (id, name) VALUES
  ('00000000-0000-0000-0000-000000000001', 'default')
ON CONFLICT DO NOTHING;
```
