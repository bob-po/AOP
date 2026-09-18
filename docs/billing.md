# Billing（Phase 26）

从 `tasks` / `agent_runs` 聚合用量并按价表估算 USD。发票预览见 [billing-invoice.md](./billing-invoice.md)。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/billing/usage?days=30` | 窗口内 tasks / agent_runs 与预估费用 |
| `GET` | `/v1/billing/summary` | `d7` + `d30` 两套 usage |

数据源：`tasks`、`agent_runs`（按 `task_nodes.skill` 聚合）。  
同时返回 `stored_cost_usd`（`agent_runs.cost_usd` 求和，若 Worker 写入）与基于价表的 `estimated_*`。

## 定价

默认价表（可用环境变量覆盖）：

| 项 | 默认 USD |
|----|----------|
| 每创建 task | 0.02 |
| agent_run（未知 skill） | 0.01 |
| `web-search` | 0.005 |
| `knowledge-search` | 0.008 |
| `business-analysis` | 0.015 |
| `report-generation` | 0.02 |
| `text-to-image` | 0.03 |
| `text-to-video` | 0.05 |

```bash
export BILLING_PRICES_JSON='{"task_created":0.03,"per_skill":{"web-search":0.01}}'
```

## Console

Settings → **用量**：7d / 30d / 90d 切换，展示合计、任务数、按 skill 明细。

## 冒烟

```bash
python apps/orchestrator/scripts/phase26_billing.py
```
