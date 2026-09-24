# Architecture（索引）

完整技术方案见 [a2a-platform-v1-design.md](./a2a-platform-v1-design.md)。  
A2A OS 演进见 [a2a-os-architecture-analysis.md](./a2a-os-architecture-analysis.md)。

## 当前落地栈

```
Web Console (Next.js :3000)
        │
        ▼
Gateway (Go :8080)
  Agents / Auth / RBAC / Audit / Session
  Proxy → Orchestrator(s) · capacity/reliability/skills
        │
        ▼
Orchestrator (Python :8090)
  Planner · Router v3 · Scheduler · Execution · Lifecycle
  Governance · Tenant/Cost · Marketplace/Skills
  Billing · Quotas · Invoice/Stripe · Egress · HITL
        │
        ├── Worker ← Redis Streams
        ├── PostgreSQL (migrations)
        ├── Redis (队列 / 锁 / PubSub)
        └── MinIO (Artifacts)
                │
                ▼
        A2A Agents :8001–8008 (+ start-agent)
```

## 专项设计

| 文档 | 内容 |
|------|------|
| [database.md](../reference/database.md) | ER / SQL / migrate |
| [redis.md](../reference/redis.md) | Streams / 锁 / Skill 索引 |
| [api.md](../reference/api.md) | Gateway + Orchestrator API |
| [mvp-plan.md](./mvp-plan.md) | Phase 1–34 进度与验收 |
| [billing.md](../reference/billing.md) · [billing-invoice.md](../reference/billing-invoice.md) | 用量与 Stripe |
| [quotas.md](../reference/quotas.md) · [egress.md](../reference/egress.md) | 配额与出站 |
| [agent-sandbox.md](./agent-sandbox.md) | 沙箱 / seccomp |
| [a2a-protocol.md](./a2a-protocol.md) | A2A 协议约定 |
| [agent-dev-guide.md](./agent-dev-guide.md) | Agent 开发规范 |
| [monitoring.md](../operations/monitoring.md) | Prometheus / Grafana |

## A2A OS 交付（Phase 3–6）

| Phase | 文档 |
|-------|------|
| 3 Execution / Lifecycle | [delivery-report](../phases/phase-03/delivery-report.md) |
| 4 Production readiness | [production-readiness](../phases/phase-04/production-readiness.md) |
| 5 Scheduling / Tenant / Cost | [delivery-report](../phases/phase-05/delivery-report.md) |
| 6 Marketplace / Skills | [delivery-report](../phases/phase-06/delivery-report.md) |
