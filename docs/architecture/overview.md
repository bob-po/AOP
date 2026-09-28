# Architecture（索引）

完整技术方案见 [a2a-platform-v1-design.md](./a2a-platform-v1-design.md)。  
A2A OS 演进见 [a2a-os-architecture-analysis.md](./a2a-os-architecture-analysis.md)。  
协议兼容见 [a2a-protocol.md](./a2a-protocol.md)。

## 分层原则

| 平面 | 职责 | 传输 |
|------|------|------|
| **OS 控制面** | 注册、发现、路由、DAG、HITL、治理、计费 | Gateway/Orchestrator REST `/v1/*` |
| **A2A Agent 面** | Agent Card 发现、任务通信 | JSON-RPC（`message/send` · `message/stream` · `tasks/*`） |
| **Edge** | 本机拉起 harness、心跳、白名单执行 | `aop-node` → Gateway 注册；子进程仍是 A2A Server |

## 当前落地栈

```text
Web Console (Next.js :3000)
        │
        ▼
Gateway (Go :8080)
  Agents / Auth / RBAC / Audit / Session
  Proxy → Orchestrator · capacity / reliability / skills
        │
        ▼
Orchestrator (Python :8090)
  Planner · Router · Scheduler · Execution · Lifecycle
  Governance · Marketplace · Billing · Quotas · HITL
        │
        ├── Worker ← Redis Streams
        ├── Outbox Processor ← PG outbox_events
        ├── PostgreSQL
        ├── Redis
        └── MinIO (Artifacts)
                │
                ▼
     Harness agents :8011–8015
       claude-code · deepseek-harness · pi · openclaw · hermes
                ▲
                │（可选）
         aop-node Supervisor :7920
           拉起插件/子进程 · 注册 · 心跳
```

## 专项设计

| 文档 | 内容 |
|------|------|
| [a2a-protocol.md](./a2a-protocol.md) | 官方 A2A 钉扎 · 支持矩阵 · Part.`kind` |
| [agent-dev-guide.md](./agent-dev-guide.md) | 合规 Agent Card · 生命周期 |
| [harness-migration.md](./harness-migration.md) | Harness 虚拟 Agent · 环境变量 · Edge |
| [agent-sandbox.md](./agent-sandbox.md) | 沙箱 / seccomp |
| [database.md](../reference/database.md) | ER / SQL / migrate |
| [redis.md](../reference/redis.md) | Streams / 锁 / Skill 索引 |
| [api.md](../reference/api.md) | Gateway + Orchestrator API |
| [mvp-plan.md](./mvp-plan.md) | Phase 1–34 进度与验收 |
| [billing.md](../reference/billing.md) · [billing-invoice.md](../reference/billing-invoice.md) | 用量与 Stripe |
| [quotas.md](../reference/quotas.md) · [egress.md](../reference/egress.md) | 配额与出站 |
| [monitoring.md](../operations/monitoring.md) | Prometheus / Grafana |
| [aop-node](../../apps/client/aop-node/README.md) | 边缘 Supervisor |

## A2A OS 交付（Phase 3–6）

| Phase | 文档 |
|-------|------|
| 3 Execution / Lifecycle | [delivery-report](../phases/phase-03/delivery-report.md) |
| 4 Production readiness | [production-readiness](../phases/phase-04/production-readiness.md) |
| 5 Scheduling / Tenant / Cost | [delivery-report](../phases/phase-05/delivery-report.md) |
| 6 Marketplace / Skills | [delivery-report](../phases/phase-06/delivery-report.md) |
