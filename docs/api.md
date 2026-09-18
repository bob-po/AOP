# API 设计（Gateway）

> 配套文档：[技术方案主文档](./A2A-Agent-调度平台-v1.0-技术方案.md)  
> 状态：**已落地至 Phase 34**（鉴权 / RBAC / Billing / Quotas / Stripe / Egress）

**Base：** `/v1`  
**Auth：** `Authorization: Bearer <api_key>` 或 `X-API-Key: <api_key>`  
**本地开关：** `go run` 默认 `AUTH_REQUIRED=false`；部署 compose 默认 `true`  
**公开路径：** `/` · `/health` · `/metrics`（Prometheus）  
**写接口 scope：** `agent.write`（注册/启停 Agent）· `task.write`（创建任务/审批/评估等）· `api_key.admin`/`admin`（密钥管理）  
**角色（Phase 23）：** `role:viewer` / `role:operator` / `role:admin`（创建 Key 时可传 `role`，鉴权时展开为 scopes）  
**开发密钥：** `SEED_DEV_KEY=true` 时种子本地 key（日志只打 prefix；scopes=`*`）  
**通用响应：** JSON；错误体多为 `{ "detail": { "code", "message" } }`（FastAPI）或 Gateway 统一错误包装

Gateway 将以下路径 **反向代理** 到 Orchestrator（默认 `:8090`）：

`/v1/tasks*` · `/v1/workflows*` · `/v1/marketplace*` · `/v1/artifacts*` · `/v1/evaluations*` · `/v1/stats*` · `/v1/billing*` · `/v1/quotas*` · `/v1/egress*` · `/v1/memory*` · `/v1/router*` · `/v1/metrics*` · `/v1/health/probe`

Agent / API Key / Auth / RBAC / Audit 由 Gateway 本机处理。

---

## 1. 路由总览

```
Gateway (:8080)
├── GET  /health
├── /v1/agents*          # Registry（本机）
├── /v1/api-keys*        # API Key（本机）
├── /v1/tasks*           # → Orchestrator
├── /v1/workflows*
├── /v1/marketplace*
├── /v1/artifacts*
├── /v1/evaluations*
├── /v1/stats*
├── /v1/billing*
├── /v1/quotas*
├── /v1/router*
├── /v1/metrics*
└── POST /v1/health/probe
```

---

## 2. Task API

### 2.1 创建 Task

`POST /v1/tasks`

```json
{
  "input": { "type": "text", "content": "分析公司A并生成报告" },
  "title": "可选标题",
  "options": {}
}
```

**响应 `201`：** 含 `task_id`、`status`、`plan`、`ready_nodes`、`enqueued_nodes`、`nodes`。

创建时写入工作记忆 `goal`；Planner 对 `HITL_SKILLS`（默认 `report-generation`）节点标记 `requires_approval`。

### 2.2 查询 / 列表 / 取消

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/tasks?status=&limit=` | 任务列表 |
| `GET` | `/v1/tasks/{task_id}` | 详情（含 nodes / plan / result） |
| `POST` | `/v1/tasks/{task_id}/cancel` | 取消；终态后自动 Evaluation |

**Task / Node 状态（节选）：**

| 状态 | 含义 |
|------|------|
| `running` / `ready` / `planned` | 执行中 |
| `waiting_for_user` | HITL 待审批 |
| `completed` / `failed` / `cancelled` | 终态 |
| 节点 `waiting_for_user` | 节点产出后等待 Approve/Reject |

### 2.3 HITL

```
POST /v1/tasks/{task_id}/approve   { "node_key": null }
POST /v1/tasks/{task_id}/reject    { "node_key": null, "reason": "..." }
```

批准后解锁下游并重新入队；驳回则 Task `failed` 并评分。

### 2.4 Trace / Artifacts

```
GET /v1/tasks/{task_id}/events
GET /v1/tasks/{task_id}/artifacts
GET /v1/artifacts?task_id=&type=&limit=
```

Console 使用 **轮询** events（非 WebSocket）。

### 2.5 Evaluation（Phase 10）

```
POST /v1/tasks/{task_id}/evaluate?method=heuristic
GET  /v1/tasks/{task_id}/evaluation
GET  /v1/evaluations?limit=&min_score=
GET  /v1/evaluations/overview
```

终态（completed / failed / cancelled）由 Worker 或 Cancel/Reject 自动写入 `task_evaluations`。

### 2.6 Memory（Phase 12）

```
GET    /v1/tasks/{task_id}/memory
PUT    /v1/tasks/{task_id}/memory          { "memory_key", "content", "metadata?" }
DELETE /v1/tasks/{task_id}/memory/{key}
```

Worker 在节点成功后写入 `node:{node_key}` 摘要，执行时注入 Working Memory。

### 2.7 Tenant Memory（Phase 20）

跨任务长期记忆（`tenant_memories`），混合 TF-IDF 检索。

```
GET    /v1/memory?limit=
PUT    /v1/memory                          { "memory_key", "content", "title?", "metadata?" }
GET    /v1/memory/search?q=&top_k=
DELETE /v1/memory/{key}
POST   /v1/tasks/{task_id}/memory/promote  # 将任务 goal/node 摘要提升到租户记忆
```

创建任务时默认召回相关租户记忆写入 `recalled`；任务 `completed` 时默认 `promote`。  
开关：`TENANT_MEMORY_RECALL` / `TENANT_MEMORY_PROMOTE`（默认 `1`）。

---

## 3. Agent API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/agents?skill=&status=` | 列表 |
| `GET` | `/v1/agents/{id}` | 详情 |
| `POST` | `/v1/agents/register` | `{ "endpoint" }` → 拉 Card → 入库 |
| `POST` | `/v1/agents/{id}/enable` / `disable` | 启用 / 禁用 |
| `POST` | `/v1/agents/{id}/health` | 主动探测 |
| `DELETE` | `/v1/agents/{id}` | 删除 |

注册流程：拉取 Agent Card → 解析 Skills → 写 PG + Redis Skill Set → Health → Online。

---

## 4. Workflow API（Phase 7 · 已落地）

```
GET  /v1/workflows?status=
POST /v1/workflows                 # name, description, dag, version, publish
GET  /v1/workflows/{workflow_id}
POST /v1/workflows/{workflow_id}/run   { "input": { "type","content" }, "title?" }
```

`run` 跳过 Planner，直接用模板 `dag_json` 建 Task 并入队。

---

## 5. Marketplace / Health（Phase 7b）

```
GET  /v1/marketplace?q=
POST /v1/marketplace/install       { "package_id"? , "endpoint"? }
POST /v1/health/probe              # 批量探测已注册 Agent
```

---

## 6. Router / Stats / Metrics（Phase 11–12）· Billing（Phase 26）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/router/preview?skill=` | 智能路由候选与 score 分解 |
| `GET` | `/v1/stats/overview` | Dashboard KPI |
| `GET` | `/v1/stats/agents?limit=` | agent_runs 窗口成功率 / 延迟 |
| `GET` | `/v1/metrics?hours=24` | 观测快照 JSON |
| `GET` | `/v1/metrics?format=prometheus` | Prometheus 文本 |
| `GET` | `/v1/billing/usage?days=30` | 租户用量预估（tasks + agent_runs） |
| `GET` | `/v1/billing/summary` | 7d / 30d 摘要 |
| `GET` | `/v1/billing/invoice?days=` | 发票预览 JSON（Phase 30） |
| `GET` | `/v1/billing/invoice.md?days=` | 发票 Markdown |
| `POST` | `/v1/billing/invoices` | 持久化发票快照 |
| `GET` | `/v1/billing/invoices` | 发票列表 |
| `POST` | `/v1/billing/invoices/{id}/checkout` | Stripe Checkout（Phase 31） |
| `GET` | `/v1/billing/checkouts` | Checkout 记录 |
| `POST` | `/v1/billing/webhooks/stripe` | Stripe Webhook（公开，Phase 32） |
| `POST` | `/v1/billing/checkouts/simulate-paid` | 本地标记已支付 |
| `GET` | `/v1/quotas` | 租户配额 + 当日用量（Phase 28） |
| `PUT` | `/v1/quotas` | 更新配额限额 |
| `GET` | `/v1/egress` | 租户出站策略（Phase 34） |
| `PUT` | `/v1/egress` | 更新 mode/patterns |
| `GET` | `/v1/egress/check?url=` | 单 URL 判定 |

Router 评分维度（`ROUTER_SMART=true`）：availability · success_rate · latency · priority。

Billing 定价：`BILLING_PRICES_JSON`（可选）覆盖默认单价；返回值为**预估**，非真实扣款。详见 `docs/billing.md` · `docs/billing-invoice.md`。  
Stripe：`STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`；Webhook 路径无需 API Key。  
配额：`TENANT_QUOTAS`；超限创建任务返回 429。详见 `docs/quotas.md`。  
出站：`TENANT_EGRESS`；`browser-automation` URL 按租户 allow/deny。详见 `docs/egress.md`。

---

## 7. Auth / API Keys（Phase 8）· RBAC（Phase 23）

```
GET    /v1/api-keys
POST   /v1/api-keys     { "name", "role"?: "viewer|operator|admin", "scopes"?: ["*"] }
DELETE /v1/api-keys/{id}
GET    /v1/rbac/roles
GET    /v1/rbac/me
GET    /v1/audit-logs?limit=
POST   /v1/auth/login     { "email", "password" }  → session token
POST   /v1/auth/logout
GET    /v1/auth/me
```

创建时明文 `api_key` 仅返回一次；库中存 SHA-256 `key_hash`。  
`role` 会归一为 `role:<name>` 写入 scopes，鉴权时展开。  
写操作（API Key / Agent）写入 `audit_logs`（Phase 24）。  
用户登录（Phase 25）：返回 `aop_sess_*` Bearer；与 API Key 共用鉴权中间件。开发账号 `admin@aop.local` / `aop_admin_dev`。

Admin 面板 `/admin/v1/*` **尚未实现**。

---

## 8. 权限点（Scopes）与角色

| Role | 展开 scopes |
|------|-------------|
| `viewer` | `task.read` · `agent.read` · `memory.read` |
| `operator` | 上表 + `.write` |
| `admin` | `*` |

| Scope | 含义 |
|-------|------|
| `*` | 开发种子全权限 |
| `task.read` / `task.write` | 读 / 创建取消任务 |
| `agent.read` / `agent.write` / `agent.register` | Agent |
| `memory.read` / `memory.write` | 租户记忆 |
| `admin` / `api_key.admin` | 管理接口 |

---

## 9. Agent 侧 A2A 接口（对端）

```
GET  {agent.url}/.well-known/agent-card.json   # 兼容 agent.json
POST {agent.url}/                              # JSON-RPC message/send
```

封装于 `packages/a2a-sdk`。详见 [a2a.md](./a2a.md)。

---

## 10. 错误码（初版）

| code | HTTP | 说明 |
|------|------|------|
| `unauthorized` | 401 | 未认证 |
| `forbidden` | 403 | 无权限 |
| `not_found` | 404 | 资源不存在 |
| `validation_error` | 400 | 参数错误 |
| `not_terminal` / `hitl_error` | 409 | 状态冲突 |
| `agent_unavailable` | 503 | 无可用 Agent |
| `storage_error` / `install_failed` | 502 | 下游失败 |
| `internal_error` | 500 | 内部错误 |

---

## 11. 冒烟脚本

```bash
cd apps/orchestrator
python scripts/phase8_auth.py
python scripts/phase9_console_api.py
python scripts/phase10_evaluation.py
python scripts/phase11_smart_hitl.py
python scripts/phase12_memory_obs.py
```
