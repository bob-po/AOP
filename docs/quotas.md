# Tenant Quotas（Phase 28）

按租户限制任务创建与用量，超限返回 **HTTP 429**。

## 表

`tenant_quotas`（迁移 `007_tenant_quotas.sql`）

| 字段 | 默认 | 含义 |
|------|------|------|
| `max_tasks_per_day` | 100 | 当日新建 tasks |
| `max_agent_runs_per_day` | 500 | 当日 agent_runs |
| `max_concurrent_tasks` | 20 | `created`/`running`/`waiting_for_user` |
| `max_estimated_usd_per_month` | 100 | 近 30 天 Billing 预估 USD |
| `enabled` | true | 行级开关 |

全局开关：`TENANT_QUOTAS`（默认 `1`）。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/quotas` | limits + usage + headroom |
| `PUT` | `/v1/quotas` | 更新限额 |

创建 Task / 运行 Workflow 前调用 `QuotaService.assert_can_create_task`；超限：

```json
{ "code": "quota_tasks_per_day", "message": "…", "quota": { … } }
```

## Console

Settings → **配额**：查看用量并编辑限额。

## 冒烟

```bash
python apps/orchestrator/scripts/phase28_quotas.py
```
