# AOP 文档中心

仓库**唯一**的项目文档树。根目录只保留 [`README.md`](../README.md)。  
组件内 `README.md`（`apps/*`、`agents/*`、`packages/*`）留在原处。

---

## 目录规范

```text
docs/
├── README.md          ← 本索引
├── guides/            ← 上手与排障
├── architecture/      ← 架构 / 协议 / Agent / Harness
├── reference/         ← API · DB · Redis · 计费契约
├── operations/        ← 监控 · 追踪 · 高可用
└── phases/            ← 分阶段交付归档
```

| 目录 | 放什么 | 不放什么 |
|------|--------|----------|
| `guides/` | 启动、错误处理 | 一次性提示词、过期进度流水账 |
| `architecture/` | 仍有效的系统设计 | Phase 验收草稿 |
| `reference/` | 稳定契约 | 实验笔记 |
| `operations/` | 部署与可观测 | 产品功能说明 |
| `phases/` | 交付结论 / 审计 / 基准；历史阶段一篇 summary | 多份中间 acceptance 草稿 |

**命名：** `kebab-case`；Phase 目录 `phase-NN`。  
**链接：** 相对路径；根 README 只链现行文档。

---

## 按读者找文档

| 你想… | 去读 |
|-------|------|
| 把本机跑起来 | [getting-started.md](./guides/getting-started.md) |
| 理解系统分层 | [overview.md](./architecture/overview.md) |
| 对接官方 A2A | [a2a-protocol.md](./architecture/a2a-protocol.md) |
| 写 / 挂一个 Agent | [agent-dev-guide.md](./architecture/agent-dev-guide.md) · [agent-approval.md](./architecture/agent-approval.md) · [harness-migration.md](./architecture/harness-migration.md) |
| 装边缘节点 aop-node | [apps/client/aop-node/README.md](../apps/client/aop-node/README.md) |
| 查 API / 表结构 | [api.md](./reference/api.md) · [database.md](./reference/database.md) |
| 单机云部署 | [deployments/README.md](../deployments/README.md) |

---

## Guides

| 文档 | 说明 |
|------|------|
| [getting-started.md](./guides/getting-started.md) | 本地完整启动 · 端口 · 环境变量 · 排障 · Chaos 恢复 · golden_demo |
| [error-handling.md](./guides/error-handling.md) | 错误处理约定 |

## Architecture

| 文档 | 说明 |
|------|------|
| [overview.md](./architecture/overview.md) | 落地架构索引（含 Edge） |
| [a2a-platform-v1-design.md](./architecture/a2a-platform-v1-design.md) | v1.0 技术方案 |
| [a2a-os-architecture-analysis.md](./architecture/a2a-os-architecture-analysis.md) | A2A OS 能力演进 |
| [a2a-protocol.md](./architecture/a2a-protocol.md) | 官方 A2A 兼容约定（钉扎 spec） |
| [agent-dev-guide.md](./architecture/agent-dev-guide.md) | Agent Card / 开发规范 |
| [agent-approval.md](./architecture/agent-approval.md) | 四种审批门 · `/v1/approvals` · 新 Agent 清单 |
| [harness-migration.md](./architecture/harness-migration.md) | Harness 虚拟 Agent · 环境变量 |
| [agent-sandbox.md](./architecture/agent-sandbox.md) | seccomp / 隔离 |
| [mvp-plan.md](./architecture/mvp-plan.md) | Phase 1–34 验收表 |

## Reference · Operations

| 文档 | 说明 |
|------|------|
| [api.md](./reference/api.md) · [database.md](./reference/database.md) · [redis.md](./reference/redis.md) | 核心契约 |
| [billing.md](./reference/billing.md) · [billing-invoice.md](./reference/billing-invoice.md) · [quotas.md](./reference/quotas.md) · [egress.md](./reference/egress.md) | 商业与租户 |
| [monitoring.md](./operations/monitoring.md) · [tracing.md](./operations/tracing.md) · [high-availability.md](./operations/high-availability.md) · [chaos-checklist.md](./operations/chaos-checklist.md) | 运维 |

## 组件 README（包内）

| 组件 | 说明 |
|------|------|
| [apps/gateway](../apps/gateway/README.md) | Go Gateway |
| [apps/orchestrator](../apps/orchestrator/README.md) | Python 编排 |
| [apps/web](../apps/web/README.md) | Next.js Console |
| [apps/client/aop-node](../apps/client/aop-node/README.md) | Rust 边缘 Supervisor |
| [agents/harness-agent](../agents/harness-agent/README.md) | 唯一 Agent 部署形态 |
| [packages/a2a-sdk](../packages/a2a-sdk/README.md) | A2A JSON-RPC SDK |
| [packages/agent-runtime](../packages/agent-runtime/README.md) | Harness + 协作运行时 |

## Phases（归档）

| Phase | 入口 |
|-------|------|
| A2A OS 3 Execution | [delivery-report](./phases/phase-03/delivery-report.md) |
| A2A OS 4 Production | [production-readiness](./phases/phase-04/production-readiness.md) |
| A2A OS 5 Scheduling | [delivery-report](./phases/phase-05/delivery-report.md) · [audit](./phases/phase-05/architecture-audit.md) · [benchmark](./phases/phase-05/benchmark.md) |
| A2A OS 6 Marketplace | [delivery-report](./phases/phase-06/delivery-report.md) · [audit](./phases/phase-06/architecture-audit.md) |
| 平台 35–37 | [35](./phases/phase-35/summary.md) · [36](./phases/phase-36/summary.md) · [37](./phases/phase-37/summary.md) |

---

## 新增 / 清理检查清单

1. 组件说明 → 留在包内 `README.md`。  
2. 根目录临时 md/json → **禁止**。  
3. 新文档登记到本索引。  
4. 文件名 `kebab-case`。  
5. 过程草稿 → **删**，只留一篇结论。
