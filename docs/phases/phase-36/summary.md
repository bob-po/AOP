# Phase 36 摘要

**主题：** 端到端可靠性（Execution Record、幂等、Outbox、重试/超时、故障验收）  
**结论：** 目标能力已并入 Orchestrator；后续由 **Phase 3–4**（Execution / Recovery）与现行测试承接，本目录不再保留过程草稿。

## 能力映射（现行）

| 能力 | 落点 |
|------|------|
| Execution Record / 幂等 | `apps/orchestrator/execution/` · `request_tracking` |
| Outbox / 可靠投递 | Orchestrator outbox + worker |
| Retry / Timeout / Recover | `execution/retry.py` · `ExecutionService` |
| 可观测 | `observability/` · `deployments` Prometheus/Grafana |

生产部署以 [`deployments/README.md`](../../../deployments/README.md) 与 [`operations/`](../../operations/) 为准。

多份 acceptance / e2e / roadmap 中间稿已删除。

返回 [文档中心](../../README.md)。
