# Architecture（索引）

完整架构说明见：

→ [《A2A Agent 调度平台 v1.0 技术方案》](./A2A-Agent-调度平台-v1.0-技术方案.md)

## 当前落地栈（Phase 34）

```
Web Console (Next.js :3000)
        │
        ▼
Gateway (Go :8080)
  Agents / API Keys / Auth / RBAC / Audit / Session
  Load-balanced reverse proxy → Orchestrator(s)
        │
        ▼
Orchestrator (Python :8090)
  Planner v2 · Router · Scheduler · Aggregator
  Evaluation · Task/Tenant Memory · Metrics
  Billing · Quotas · Invoice/Stripe · Egress
  Marketplace · Workflows · HITL
        │
        ├── Worker ← Redis Streams (a2a.execution.queue)
        ├── PostgreSQL (权威状态 + migrations 000–012)
        ├── Redis (队列 / Skill 索引 / 锁 / PubSub)
        └── MinIO (Artifacts)
                │
                ▼
        A2A Agents :8001–8008
        (search … video · code · browser)
```

## 专项设计

| 文档 | 内容 |
|------|------|
| [database.md](./database.md) | ER / SQL / migrate |
| [redis.md](./redis.md) | Streams / 锁 / Skill 索引 |
| [api.md](./api.md) | Gateway + Orchestrator API |
| [mvp-plan.md](./mvp-plan.md) | Phase 1–34 进度与验收 |
| [billing.md](./billing.md) · [billing-invoice.md](./billing-invoice.md) | 用量与 Stripe |
| [quotas.md](./quotas.md) · [egress.md](./egress.md) | 配额与出站 |
| [agent-sandbox.md](./agent-sandbox.md) | 沙箱 / seccomp |
| [a2a.md](./a2a.md) | A2A 协议约定 |
| [agent.md](./agent.md) | Agent 开发规范 |
| [monitoring-setup.md](./monitoring-setup.md) | Prometheus / Grafana |

## 关键路径（简图）

```
Client → Gateway(:8080) → Orchestrator(:8090) → Worker → Agent(:800x)
                │                    │
                └── /v1/agents*      └── PG / Redis / MinIO
```
