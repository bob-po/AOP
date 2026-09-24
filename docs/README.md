# AOP 文档中心

仓库**唯一**的项目文档树。根目录只保留 [`README.md`](../README.md)。  
组件内 `README.md`（`apps/*`、`agents/*`、`packages/*`）留在原处。

---

## 目录规范

```text
docs/
├── README.md          ← 本索引
├── guides/            ← 上手与运维向导
├── architecture/      ← 架构 / 协议 / Agent
├── reference/         ← API · DB · Redis · 计费契约
├── operations/        ← 监控 · 追踪 · 高可用
└── phases/            ← 分阶段交付（现行 03–06；历史 35–37 仅留摘要）
```

| 目录 | 放什么 | 不放什么 |
|------|--------|----------|
| `guides/` | 启动、错误处理 | 一次性提示词、过期进度流水账 |
| `architecture/` | 仍有效的系统设计 | Phase 验收草稿 |
| `reference/` | 稳定契约 | 实验笔记 |
| `operations/` | 部署与可观测 | 产品功能说明 |
| `phases/` | 交付结论 / 审计 / 基准；历史阶段**一篇 summary** | 多份中间 acceptance / e2e 草稿 |

**命名：** `kebab-case`；Phase 目录 `phase-NN`；现行报告优先 `delivery-report.md` / `architecture-audit.md` / `benchmark.md`。

**链接：** 相对路径；根 README 只链现行文档，不链过期草稿。

---

## 快速入口

### Guides

| 文档 | 说明 |
|------|------|
| [getting-started.md](./guides/getting-started.md) | 项目启动 |
| [error-handling.md](./guides/error-handling.md) | 错误处理 |

### Architecture

| 文档 | 说明 |
|------|------|
| [overview.md](./architecture/overview.md) | 落地架构索引 |
| [a2a-platform-v1-design.md](./architecture/a2a-platform-v1-design.md) | v1.0 技术方案 |
| [a2a-os-architecture-analysis.md](./architecture/a2a-os-architecture-analysis.md) | A2A OS 分析 |
| [a2a-protocol.md](./architecture/a2a-protocol.md) | 协议约定 |
| [agent-dev-guide.md](./architecture/agent-dev-guide.md) | Agent 开发 |
| [agent-sandbox.md](./architecture/agent-sandbox.md) | 沙箱 |
| [mvp-plan.md](./architecture/mvp-plan.md) | Phase 1–34 验收表 |

### Reference · Operations

| 文档 | 说明 |
|------|------|
| [api.md](./reference/api.md) · [database.md](./reference/database.md) · [redis.md](./reference/redis.md) | 核心契约 |
| [billing.md](./reference/billing.md) · [billing-invoice.md](./reference/billing-invoice.md) · [quotas.md](./reference/quotas.md) · [egress.md](./reference/egress.md) | 商业与租户 |
| [monitoring.md](./operations/monitoring.md) · [tracing.md](./operations/tracing.md) · [high-availability.md](./operations/high-availability.md) | 运维 |
| [deployments/README.md](../deployments/README.md) | 部署 |

### Phases

| Phase | 入口 |
|-------|------|
| 3 | [delivery-report.md](./phases/phase-03/delivery-report.md) |
| 4 | [production-readiness.md](./phases/phase-04/production-readiness.md) |
| 5 | [delivery-report.md](./phases/phase-05/delivery-report.md) · [audit](./phases/phase-05/architecture-audit.md) · [benchmark](./phases/phase-05/benchmark.md) |
| 6 | [delivery-report.md](./phases/phase-06/delivery-report.md) · [audit](./phases/phase-06/architecture-audit.md) |
| 35–37 | [phase-35/summary](./phases/phase-35/summary.md) · [phase-36/summary](./phases/phase-36/summary.md) · [phase-37/summary](./phases/phase-37/summary.md) |

---

## 新增 / 清理检查清单

1. 组件 README？→ 留在包内。  
2. 根目录临时 md/json？→ **禁止**。  
3. 登记到本索引。  
4. `kebab-case`。  
5. 过程草稿（多版本 acceptance、提示词、重复基准）→ **删**，只留一篇结论。
