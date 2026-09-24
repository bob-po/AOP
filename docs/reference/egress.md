# Tenant Egress（Phase 34）

按租户限制 **browser-automation** 输入中的出站 URL。Worker 在 A2A 调用前由沙箱调用 `EgressService.assert_query_allowed`。

## 表

`tenant_egress_policies`（`012_tenant_egress.sql`）

| 字段 | 说明 |
|------|------|
| `mode` | `open` / `allowlist` / `denylist` |
| `patterns` | 逗号分隔 host，支持 `*.suffix` |
| `enabled` | 行级开关 |

全局开关：`TENANT_EGRESS`（默认 `1`）。

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/egress` | 当前策略 |
| `PUT` | `/v1/egress` | `{ mode, patterns, enabled }` |
| `GET` | `/v1/egress/check?url=` | 单 URL 判定 |

违规时节点失败：`sandbox: egress: …`。

## Console

Settings → **出站**。

## 冒烟

```bash
python apps/orchestrator/scripts/phase34_egress.py
```
