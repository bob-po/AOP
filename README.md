# A2A Agent Orchestration Platform (AOP)

基于 A2A 协议的多 Agent **注册 · 发现 · 调度 · 编排 · 执行** 平台。

当前进度：**Phase 1–34**（鉴权 / 计费 / 配额 / 沙箱 / Stripe）+ **A2A OS Phase 3–6**（Execution · Scheduling · Marketplace）。

## 文档

完整索引与目录规范见 **[docs/README.md](./docs/README.md)**。

| 文档 | 说明 |
|------|------|
| [文档中心](./docs/README.md) | 索引 · 分类规范 · Phase 归档 |
| [启动指南](./docs/guides/getting-started.md) | 本地与环境启动 |
| [架构总览](./docs/architecture/overview.md) | 落地架构索引 |
| [技术方案 v1.0](./docs/architecture/a2a-platform-v1-design.md) | 总体架构与设计决策 |
| [A2A OS 分析](./docs/architecture/a2a-os-architecture-analysis.md) | Agent OS 能力演进 |
| [MVP / Phase 计划](./docs/architecture/mvp-plan.md) | Phase 1–34 任务与验收 |
| [API](./docs/reference/api.md) | Gateway REST API |
| [Database](./docs/reference/database.md) | PostgreSQL 表结构与迁移 |
| [Redis](./docs/reference/redis.md) | Streams / 队列 / 锁 |
| [A2A 协议](./docs/architecture/a2a-protocol.md) | 协议落地约定 |
| [Agent 开发](./docs/architecture/agent-dev-guide.md) | Agent 开发规范 |
| [沙箱](./docs/architecture/agent-sandbox.md) | seccomp / 隔离 |
| [Billing](./docs/reference/billing.md) · [Invoice](./docs/reference/billing-invoice.md) | 用量 · 发票 · Stripe |
| [Quotas](./docs/reference/quotas.md) | 租户配额 |
| [Egress](./docs/reference/egress.md) | 租户出站策略 |
| [Monitoring](./docs/operations/monitoring.md) | Prometheus / Grafana |
| [Phase 6 交付](./docs/phases/phase-06/delivery-report.md) | Marketplace / Skill / Discovery |

## 仓库结构

```
apps/           gateway (Go) · orchestrator (Python) · web (Next.js)
agents/         search · rag · report · analysis · image · video · code · browser
packages/       a2a-sdk · schemas · common
infrastructure/ postgres（migrate.py + init/*.sql）· redis · minio
deployments/    docker-compose · deploy.sh · seccomp · observability
docs/           文档中心（guides · architecture · reference · operations · phases）
scripts/        start_and_register_agents.py
```

文档规范见 [docs/README.md](./docs/README.md)。根目录除本 README 外不存放项目 Markdown。

## 快速开始（本地）

### 1. 基础设施

```bash
docker compose -f deployments/docker-compose.yml up -d postgres redis minio
python infrastructure/postgres/migrate.py
```

### 2. Orchestrator + Worker

```bash
cd apps/orchestrator
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8090
# 另开终端
python worker.py
```

### 3. Gateway

```bash
cd apps/gateway
# 本地默认 AUTH_REQUIRED=false；对接 Console 登录时可开 true
set ORCHESTRATOR_URL=http://127.0.0.1:8090
go run ./cmd/
```

### 4. Harness 虚拟 Agents（8011–8016）并注册

```bash
pip install -e "packages/agent-runtime[harness]"
pip install -e packages/a2a-sdk
python scripts/start_and_register_agents.py
```

| Profile | Port | Skills（摘要） |
|---------|------|----------------|
| claude-coder | 8011 | code-execution, code-assist |
| claude-researcher | 8012 | web-research, research-summarize, web-search |
| pi-coder | 8013 | code-execution, code-assist |
| pi-researcher | 8014 | web-research, research-summarize, web-search |
| deepseek-coder | 8015 | code-execution, code-assist |
| deepseek-researcher | 8016 | web-research, research-summarize, web-search |

详见 [harness-migration.md](./docs/architecture/harness-migration.md)。远端主机：`irm http://<os>:8000/install/claude-coder.ps1 | iex`

### 5. Web Console

```bash
cd apps/web
npm install
npm run dev
```

打开 http://127.0.0.1:3000  

| 路由 | 页面 |
|------|------|
| `/login` | 邮箱密码登录 |
| `/` | Dashboard |
| `/tasks` | 任务 + ReactFlow DAG |
| `/agents` | Agent 注册中心（含市场） |
| `/workflows` | 编排模板 |
| `/artifacts` | 产物仓库 |
| `/settings` | API Keys · RBAC · 审计 · 用量 · 配额 · 出站 |

默认开发账号：`admin@aop.local` / `aop_admin_dev`（需先跑迁移并 seed，见 Phase 25）。

## 云服务器单机部署

详见 [deployments/README.md](./deployments/README.md)。

```bash
cd deployments
cp .env.example .env
# 编辑 AOP_PUBLIC_HOST=<公网IP或域名>
chmod +x deploy.sh
./deploy.sh up
```

打开 `http://<AOP_PUBLIC_HOST>:3000`（部署默认 `AUTH_REQUIRED=true`）。

## 当前进度（Phase 1–34）

- [x] Phase 1–7b：A2A · Registry · Planner/DAG · Worker · Artifact · Console · Workflow · Marketplace
- [x] Phase 8–12：API Key · 六大页面 · Evaluation · 智能路由/HITL · Memory/Metrics
- [x] Phase 13–17：可靠性 · Realtime WS · 生产鉴权 · Agent 质量 · 可观测 LB
- [x] Phase 18–25：迁移纪律 · Planner v2 · Tenant Memory · Grafana · 沙箱 · RBAC · 审计 · 登录
- [x] Phase 26：Billing 用量计量（Settings「用量」）
- [x] Phase 27：Code / Browser Agent + seccomp 配置
- [x] Phase 28：租户配额（超限 HTTP 429）
- [x] Phase 29：Browser Chromium（Playwright）可选镜像
- [x] Phase 30–32：发票快照 · Stripe Checkout · Webhook 确认支付
- [x] Phase 33：支付后配额提升（`tenant_quota_grants`）
- [x] Phase 34：租户出站策略（browser URL allow/deny）

冒烟脚本：`apps/orchestrator/scripts/phase*.py`。完整验收表见 [mvp-plan.md](./docs/architecture/mvp-plan.md)。

### 常用运维提示

| 现象 | 处理 |
|------|------|
| `429` + `quota_concurrent` | Settings「配额」调高，或取消卡在 `running` 的旧任务 |
| Gateway `proxy error: dial …:8090` | 确认 Orchestrator 在听 8090；Windows 下大量轮询可能导致临时端口/`TIME_WAIT` 压力，可重启 Gateway 并减轻刷新 |
| 部署环境鉴权 | 使用 Bearer 会话或 `X-API-Key`；勿把真实 Stripe / DB 密钥提交进仓库 |

### Phase 25：多用户登录

```bash
python infrastructure/postgres/migrate.py
cd apps/orchestrator && python scripts/phase25_auth_users.py
```

| 项 | 说明 |
|----|------|
| 开发账号 | `admin@aop.local` / `aop_admin_dev`（`SEED_ADMIN_PASSWORD` 可覆盖） |
| API | `POST /v1/auth/login` · `POST /v1/auth/logout` · `GET /v1/auth/me` |
| Console | `/login`；会话存 `localStorage.aop_session_token` |

### Phase 26–34 速查

| Phase | 文档 / 冒烟 |
|-------|-------------|
| 26 Billing | [billing.md](./docs/reference/billing.md) · `phase26_billing.py` |
| 27 seccomp | [agent-sandbox.md](./docs/architecture/agent-sandbox.md) · `phase27_seccomp.py` |
| 28 Quotas | [quotas.md](./docs/reference/quotas.md) · `phase28_quotas.py` |
| 29 Chromium | ~~browser-agent~~ 已下线 · seccomp `browser-agent.json` 已移除 |
| 30–32 Invoice / Stripe | [billing-invoice.md](./docs/reference/billing-invoice.md) · `phase30`–`phase32_*.py` |
| 33 Quota boost | `phase33_quota_boost.py` |
| 34 Egress | [egress.md](./docs/reference/egress.md) · `phase34_egress.py` |

### Phase 8：API Key

本地 `go run` 默认 `AUTH_REQUIRED=false`；**单机/HA 部署默认 `AUTH_REQUIRED=true`**。开启后需带：

```bash
Authorization: Bearer aop_sk_dev_local_0000000000000001
# 或
X-API-Key: aop_sk_dev_local_0000000000000001
```

Web Console：`apps/web/.env.local` 中设置 `NEXT_PUBLIC_API_KEY`（可选；登录会话优先）。
