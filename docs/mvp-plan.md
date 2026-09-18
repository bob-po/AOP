# MVP 开发计划与任务拆分

> 配套文档：[技术方案主文档](./A2A-Agent-调度平台-v1.0-技术方案.md)  
> **状态：Phase 1–34 已落地**（Billing · Quotas · Code/Browser · Stripe · Egress；见文末进度表）

## 1. MVP 目标

跑通最小闭环：

```
用户 → 创建任务 → Planner → DAG → Router → A2A → Agent 执行 → Artifact → Task 完成 → Trace 可见
```

**第一批 Agent：** Search · RAG · Report（已扩展 Analysis / Image / Video）

**首个 Demo 提示词：**

> 帮我研究一个 AI 产品，搜索公开资料，结合知识库分析，并生成一份报告。

期望 DAG（示意）：

```
        Search ──┐
                 ├──→ Analysis → Report（HITL 可选）
        RAG ─────┘
```

---

## 2. 非目标 / 仍弱化项

| 项 | 现状 |
|----|------|
| K8s 生产编排 | 仍以 docker-compose / 单机 `deploy.sh` 为主 |
| 出站强制网关 | 租户策略已落地；iptables / sidecar 代理未做 |
| 向量库 Memory | Tenant Memory 为 TF-IDF；未接专用向量库 |
| 真实 Stripe 生产密钥 | Checkout / Webhook 支持 dry-run + live；需自行配置密钥 |

~~原 MVP「不做」但已落地：~~ Marketplace · 智能路由 · HITL · Evaluation · Memory · Metrics · Billing · Quotas · Code/Browser · Stripe · Egress · RBAC · 审计 · 登录。

---

## 3. Phase 拆分与完成状态

### Phase 1 — A2A 单 Agent 打通 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P1-1 | `packages/a2a-sdk` | 解析 Agent Card |
| P1-2 | `agents/search-agent` | 返回 Text Artifact |
| P1-3 | Orchestrator A2A Client | `scripts/call_search_agent.py` |

### Phase 2 — Registry + Router ✅

| ID | 任务 | 验收 |
|----|------|------|
| P2-1 | PG schema agents/skills/endpoints | `001_init.sql` |
| P2-2 | `POST /v1/agents/register` | 注册可查 |
| P2-3 | Skill 索引 PG + Redis Set | 按 skill 查 Agent |
| P2-4 | Router Skill Match + Online | 离线不选中 |

### Phase 3 — Planner + DAG + Scheduler ✅

| ID | 任务 | 验收 |
|----|------|------|
| P3-1–P3-5 | Task/Node/依赖 · Planner · 校验 · READY · `POST /v1/tasks` | `phase3_create_task.py` |

### Phase 4 — 异步执行 + Retry ✅

| ID | 任务 | 验收 |
|----|------|------|
| P4-1–P4-4 | Streams · Worker · Retry/Failover · Aggregator | `phase4_execute_dag.py` |

### Phase 5 — Artifact + MinIO ✅

| ID | 任务 | 验收 |
|----|------|------|
| P5-1–P5-3 | Bucket · node output · artifacts API | `phase5_artifacts.py` |

### Phase 6 — Console + Trace ✅

| ID | 任务 | 验收 |
|----|------|------|
| P6-1–P6-4 | Next.js · DAG · 轮询 Trace · Agents | `apps/web` |

### Phase 7 / 7b — Workflow · Marketplace · Health ✅

| ID | 任务 | 验收 |
|----|------|------|
| P7 | Workflow 模板 run | `phase7_workflow.py` |
| P7b | Marketplace + Health probe | `phase7b_marketplace.py` |

### Phase 8 — API Key 鉴权 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P8 | Bearer / X-API-Key · `AUTH_REQUIRED` | `phase8_auth.py` |

### Phase 9 — 六大 Console 页面 ✅

Dashboard · Tasks · Agents · Workflows · Artifacts · Settings — `phase9_console_api.py`

### Phase 10 — Evaluation ✅

启发式评分 · 终态自动评估 — `phase10_evaluation.py` · `002_evaluation.sql`

### Phase 11 — 智能路由 + HITL ✅

Score 选 Agent · `waiting_for_user` · approve/reject — `phase11_smart_hitl.py`

### Phase 12 — Memory · Observability · 长任务 ✅

`task_memories` · `/v1/metrics` · stale reclaim — `phase12_memory_obs.py` · `003_memory.sql`

### Phase 13 — Reliability & Observability Align ✅

| ID | 任务 | 验收 |
|----|------|------|
| P13-1 | pytest：DAG / Planner / Scheduler claim·HITL·retry / stale reclaim / Router score | `python scripts/phase13_reliability.py` |
| P13-2 | Worker：去掉重复 route；A2A 路径接入 Circuit Breaker | 单次 select + `get_circuit_breaker` |
| P13-3 | Prometheus 目标对齐 | `prometheus.yml`（compose 网）· `prometheus.host.yml`（宿主机）· single `observability` profile |


### Phase 14 — Realtime fan-out ✅

| ID | 任务 | 验收 |
|----|------|------|
| P14-1 | Redis Pub/Sub 替代 WS consumer-group | test_pubsub_fanout.py 双订阅者均收到 |
| P14-2 | Gateway 代理 WS；api_key query | Console 经 :8080 连 WS |
| P14-3 | useTaskLive：WS 主路径 + 轮询降级 | Tasks 页 live·ws / live·poll |

### Phase 15 — 生产鉴权基线 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P15-1 | 部署默认 `AUTH_REQUIRED=true`；`SEED_DEV_KEY` 可控 | compose / deploy.sh / .env.example |
| P15-2 | 启动日志仅打 key prefix，不打明文 | Gateway log |
| P15-3 | 写接口 scope：`agent.write` / `task.write`；`/metrics` 公开 | `phase15_auth.py` |

### Phase 16 — Agent 质量纵切 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P16-1 | Search：DDG Instant / Lite / Wikipedia + mock 降级 | `SEARCH_MODE` · `phase16_agents.py` |
| P16-2 | RAG：混合 TF-IDF 向量检索 + 扩展语料 | `vector_index.py` · citations 含 score |
| P16-3 | Marketplace / Agent Card 版本更新 | search 0.2 · rag 0.3 |

### Phase 17 — 可观测可用 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P17-1 | Gateway 健康感知 LB（探针 /health，全挂 fail-open） | go test LoadBalanced* |
| P17-2 | Worker/Service 递增 `aop_agent_calls_total` / `aop_tasks_total` | `test_observability_metrics.py` |
| P17-3 | Alert 规则对齐真实指标名 + LB 无健康后端告警 | `aop-alerts.yml` |

### Phase 18 — Schema 迁移纪律 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P18-1 | `schema_migrations` + `migrate.py`；init `000`–`003` 为唯一 DDL 源 | `--status` / apply 幂等 |
| P18-2 | 去掉 Memory / Evaluation 运行时 `ensure_schema` | `test_migrate.py` · `phase18_schema.py` |
| P18-3 | 文档与部署说明对齐 | `docs/database.md` · `infrastructure/postgres/README.md` |

### Phase 19 — Planner v2 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P19-1 | 多步目标分解（编号 / 先…再…）→ 线性 DAG | `heuristic_steps` · `test_planner_v2.py` |
| P19-2 | LLM JSON 提取/修复；非法 plan 回退 heuristic | `json_plan.py` · 不硬失败 |
| P19-3 | `PLANNER_V2` 默认开启；可关 | `phase19_planner.py` |

### Phase 20 — 跨任务 Memory ✅

| ID | 任务 | 验收 |
|----|------|------|
| P20-1 | `tenant_memories` + migrate `004` | `migrate.py` |
| P20-2 | TF-IDF 检索 API · 建任务召回 · 完成时 promote | `/v1/memory*` · `phase20_tenant_memory.py` |
| P20-3 | Gateway 代理 `/v1/memory` | server.go |

### Phase 21 — Grafana / 告警面板 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P21-1 | Overview Dashboard 对齐 live + snapshot 指标 | `overview-dashboard.json` |
| P21-2 | 抓取 Worker metrics；补充失败率 / WorkerDown 告警 | `prometheus*.yml` · `aop-alerts.yml` |
| P21-3 | `aop_tenant_memories_total` 进入快照；文档 | `phase21_observability.py` |

### Phase 22 — Agent 沙箱策略 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P22-1 | Endpoint/skill 白名单 · 输入输出截断 · 分 skill 超时 | `sandbox/` · `test_sandbox.py` |
| P22-2 | Worker/Executor 接入；Compose Agent CPU/内存限额 | `docker-compose.single.yml` |
| P22-3 | `AOP_RUNTIME=docker` 保留服务 DNS | `normalize_endpoint` · `agent-sandbox.md` |

### Phase 23 — RBAC 角色 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P23-1 | 内置角色 `viewer` / `operator` / `admin` 展开 scopes | `auth/rbac.go` |
| P23-2 | `GET /v1/rbac/roles` · `/me`；创建 Key 可带 `role` | Gateway + Settings |
| P23-3 | go test + Console 角色选择 | `phase23_rbac.py` |

### Phase 24 — 审计日志 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P24-1 | `GET /v1/audit-logs`；索引迁移 `005` | `audit.go` · migrate |
| P24-2 | Agent / API Key 写操作打点 | register/revoke/… |
| P24-3 | Settings 审计 Tab 列表 | `phase24_audit.py` |

### Phase 25 — 多用户登录 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P25-1 | `password_hash` + `user_sessions`（`006`） | migrate |
| P25-2 | `POST /v1/auth/login` · logout · me；会话 Bearer | Gateway |
| P25-3 | Console `/login` + 顶栏用户/退出 | `phase25_auth_users.py` |

### Phase 26 — Billing（用量计量） ✅

| ID | 任务 | 验收 |
|----|------|------|
| P26-1 | `BillingService`：tasks + agent_runs × 定价表 | `billing/` |
| P26-2 | `GET /v1/billing/usage` · `summary`；Gateway 代理 | Orchestrator + Gateway |
| P26-3 | Settings「用量」Tab；冒烟 | `phase26_billing.py` |

### Phase 27 — Code/Browser seccomp ✅

| ID | 任务 | 验收 |
|----|------|------|
| P27-1 | `deployments/seccomp/*.json` + Compose `cap_drop` / `no-new-privileges` | profiles |
| P27-2 | `code-agent`（AST-safe）· `browser-agent`（egress stub） | agents + marketplace |
| P27-3 | 高危 skill 宿主校验；冒烟 | `phase27_seccomp.py` |

### Phase 28 — 租户配额 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P28-1 | `tenant_quotas` 迁移 `007` | migrate |
| P28-2 | `QuotaService`；创建 Task / Workflow 429 | `quota/` |
| P28-3 | `GET/PUT /v1/quotas`；Settings 配额 Tab | `phase28_quotas.py` |

### Phase 29 — Browser Chromium（Playwright） ✅

| ID | 任务 | 验收 |
|----|------|------|
| P29-1 | `browse.py`：stub / playwright / auto + 失败回退 | unit tests |
| P29-2 | `Dockerfile.chromium` + compose override | `docker-compose.browser-chromium.yml` |
| P29-3 | 冒烟 | `phase29_browser_chromium.py` |

### Phase 30 — 发票预览 / 快照 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P30-1 | `billing_invoices` 迁移 `008` + InvoiceService | migrate |
| P30-2 | `GET/POST /v1/billing/invoice(s)` · Markdown | API |
| P30-3 | Settings 用量区发票；冒烟 | `phase30_invoice.py` |

### Phase 31 — Stripe Checkout Session ✅

| ID | 任务 | 验收 |
|----|------|------|
| P31-1 | `billing_checkout_sessions` 迁移 `009` | migrate |
| P31-2 | `create_checkout_session` live/dry-run；`POST …/checkout` | `stripe_checkout.py` |
| P31-3 | Settings Dry-run/Checkout；冒烟 | `phase31_stripe_checkout.py` |

### Phase 32 — Stripe Webhook 确认支付 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P32-1 | `010`：paid_at + `billing_webhook_events` | migrate |
| P32-2 | 验签 `POST /v1/billing/webhooks/stripe`（公开） | `webhook.py` |
| P32-3 | simulate-paid + Settings Mark paid；冒烟 | `phase32_stripe_webhook.py` |

### Phase 33 — 支付后配额提升 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P33-1 | `tenant_quota_grants` 迁移 `011` | migrate |
| P33-2 | Webhook `paid` 时按发票金额提升限额 | `quota/` |
| P33-3 | `GET /v1/quotas/grants`；冒烟 | `phase33_quota_boost.py` |

### Phase 34 — 租户出站策略 ✅

| ID | 任务 | 验收 |
|----|------|------|
| P34-1 | `tenant_egress_policies` 迁移 `012` | migrate |
| P34-2 | browser-automation URL 拦截 | `egress/` · sandbox |
| P34-3 | `GET/PUT /v1/egress`；Settings 出站；冒烟 | `phase34_egress.py` |

---

## 4. 开发顺序（回顾）

```
Phase 1 → … → 33 → 34
```

冒烟脚本目录：`apps/orchestrator/scripts/phase*.py`

---

## 5. 里程碑验收（技术方案 v1.0 核心 10 项）

| # | 标准 | 状态 |
|---|------|------|
| 1 | Agent 可以注册 | ✅ |
| 2 | Agent Card 可以读取 | ✅ |
| 3 | Agent Skill 可以发现 | ✅ |
| 4 | 用户可以创建 Task | ✅ |
| 5 | Planner 可以生成 DAG | ✅ |
| 6 | Router 可以选择 Agent | ✅（含智能评分） |
| 7 | Executor 可以进行 A2A 调用 | ✅ |
| 8 | 多 Agent 可以并行执行 | ✅ |
| 9 | Artifact 可以传递 | ✅ |
| 10 | 前端可以实时看到 Task Trace | ✅（WS + 轮询降级） |

**扩展里程碑（第三 / 四阶段）：** Workflow · Marketplace · 多租户 API Key · Evaluation · HITL · Memory · Metrics — ✅

---

## 6. 首周 Checklist（历史 · 已完成）

- [x] monorepo 目录  
- [x] docker-compose：postgres + redis + minio  
- [x] `docs/a2a.md` 规范约定  
- [x] Search Agent Hello World  
- [x] A2A Client 同步调用  
- [x] agents / tasks migration  

---

## 7. 风险与缓解（仍适用）

| 风险 | 缓解 |
|------|------|
| Planner JSON 不稳定 | Schema 约束 + 模板 fallback |
| A2A 规范细节变动 | SDK 隔离 |
| 并行调度重复派发 | Task 锁 + 条件更新 |
| Agent 超时挂起 | `A2A_TIMEOUT` + `NODE_STALE_SECONDS` 回收 |
| 评分冷启动 | 无样本时默认 success_rate / latency 先验分 |

---

## 8. 后续可选增强

1. ~~真正的 WebSocket Trace / PubSub fan-out~~（Phase 14 已完成）  
2. ~~Schema 迁移纪律（去掉运行时 DDL）~~（Phase 18 已完成）  
3. ~~Planner v2（更稳的 JSON / 多步分解）~~（Phase 19 已完成）  
4. ~~跨任务 / 租户级长期 Memory（向量检索）~~（Phase 20 已完成 · TF-IDF）  
5. ~~Grafana + Prometheus 抓取 / 告警面板~~（Phase 21 已完成）  
6. ~~Agent 沙箱策略（白名单 / 限额 / Compose 资源）~~（Phase 22 已完成）  
7. ~~可编辑 RBAC 角色（viewer/operator/admin）~~（Phase 23 已完成）  
8. ~~审计日志 API~~（Phase 24 已完成）  
9. ~~多用户登录（邮箱密码 + 会话）~~（Phase 25 已完成）  
10. ~~Billing（用量计量 / 预估）~~（Phase 26 已完成）  
11. ~~Code/Browser seccomp 沙箱~~（Phase 27 已完成）  
12. ~~租户配额~~（Phase 28 已完成）  
13. ~~Browser Chromium（Playwright）~~（Phase 29 已完成）  
14. ~~发票预览 / 快照（Stripe-shaped）~~（Phase 30 已完成）  
15. ~~Stripe Checkout Session~~（Phase 31 已完成）  
16. ~~Stripe Webhook 确认支付~~（Phase 32 已完成）  
17. ~~支付后配额提升~~（Phase 33 已完成）  
18. ~~租户出站策略~~（Phase 34 已完成）  

当前建议：出站代理网关（iptables / sidecar），或支付后邮件通知。

