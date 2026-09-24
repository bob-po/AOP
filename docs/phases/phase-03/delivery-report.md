# Phase 3 交付报告

**结论：Phase 3 PASS**（核心可靠性 / 可观测 / 生命周期能力已落地，Phase 2 hermetic 回归全绿）

---

## 1. 实施映射表

| 阶段 | 目标 | 状态 | 落点 |
|------|------|------|------|
| P3.0 | 可靠性审计 | ✅ | 复用 scheduler / governance / observability / tracing / request_tracking |
| P3.1 | Execution / Agent 状态机 | ✅ | `execution/state_machine.py` |
| P3.2 | Execution Record SoT | ✅ | `execution/record.py` + SQL `020_a2a_phase3_execution.sql` |
| P3.3 | Retry / Timeout | ✅ | `execution/retry.py` + `ExecutionService.mark_retry/timeout/apply_callback` |
| P3.4 | Recovery | ✅ | `ExecutionService.recover` + `POST /v1/tasks/{id}/recover` |
| P3.5 | Event System | ✅ | `execution/events.py` |
| P3.6 | Collaboration Graph Runtime | ✅ | `runtime_graph` edge  enrichment + lifecycle 节点态 |
| P3.7 | Structured Logging | ✅ | `logging`（execution/lifecycle）；禁止新增 print |
| P3.8 | Metrics | ✅ | `observability/a2a_metrics.py`（复用 prometheus_client） |
| P3.9 | Trace | ✅ | 复用既有 OTel `tracing/`；lineage 字段挂在 record/event |
| P3.10 | Agent Lifecycle | ✅ | `agent_lifecycle/` |
| P3.11 | Heartbeat / Health | ✅ | `/v1/agents/{id}/health|heartbeat` + gateway `/v1/agent-runtime/*` |
| P3.12 | Capacity | ✅ | lifecycle `max_concurrency` + governance check 门禁 |
| P3.13 | Cancellation | ✅ | `cancel_tree` 挂到既有 `POST /v1/tasks/{id}/cancel` |
| P3.14 | Policy Engine | ✅ | `execution/policy.py` |
| P3.15 | 测试 / 文档 | ✅ | 本报告 + 单元/可靠性测试 |

---

## 2. 新增模块

```
apps/orchestrator/execution/
  __init__.py
  state_machine.py      # ExecutionState / AgentLifecycleState + 非法转换拒绝
  record.py             # ExecutionRecord SoT（内存 + Postgres）
  events.py             # ExecutionEventBus（幂等 event_id）
  retry.py              # RetryPolicy / TimeoutPolicy
  policy.py             # CollaborationPolicy / PolicyEngine
  service.py            # ExecutionService 门面

apps/orchestrator/agent_lifecycle/
  __init__.py           # REGISTERED→READY→BUSY→DRAINING→OFFLINE

apps/orchestrator/observability/a2a_metrics.py
infrastructure/postgres/init/020_a2a_phase3_execution.sql
```

---

## 3. API 清单

| Method | Path | 说明 |
|--------|------|------|
| GET | `/v1/tasks/{id}` | 附加 `execution` 快照（兼容） |
| GET | `/v1/tasks/{id}/execution` | Execution Record 视图 |
| GET | `/v1/tasks/{id}/events` | 既有 |
| GET | `/v1/tasks/{id}/collaboration-graph` | + agent lifecycle 节点 |
| POST | `/v1/tasks/{id}/cancel` | + `execution_cancel` 级联 |
| POST | `/v1/tasks/{id}/recover` | 恢复分类 + 独占 ownership |
| GET | `/v1/collaboration/graph/{root}` | + lifecycle |
| GET | `/v1/collaboration/events/{root}` | 协作事件流 |
| GET | `/v1/agents/{id}/health` | 生命周期健康 |
| POST | `/v1/agents/{id}/heartbeat` | 心跳 |
| POST | `/v1/agents/{id}/drain` | Drain |
| GET/POST | `/v1/agent-runtime/{id}/…` | Gateway 安全别名 |

Gateway：`/v1/agent-runtime/*`、`/v1/collaboration/*`、`/v1/governance/*` 代理。

CLI（`scripts/aop.py`）：
`task events|execution|cancel|recover|graph`，`agent health|drain`。

---

## 4. State Machine

**Execution：** `PENDING → RUNNING → {WAITING|RETRYING|SUCCEEDED|FAILED|CANCELLED|TIMEOUT}`  
Terminal 保护：`SUCCEEDED` / `CANCELLED` 不可回退；`TIMEOUT`/`FAILED` 仅 recoverable 路径可进 `RETRYING`。

**Agent：** `REGISTERED → READY ⇄ BUSY → DRAINING → OFFLINE`  
`DRAINING`/`OFFLINE` 拒绝新 delegation；未登记 Agent 视为 legacy 仍允许（兼容 Phase 2）。

---

## 5. Execution Record

事实来源字段：`task_id/root/correlation/parent/agent/operation/state/attempt/max_retries/timestamps/error/idempotency_key/branch_lineage/visited_agents/ownership_token`。

原则：**Record → Event → Metrics/Logs**；禁止从日志反推状态。

---

## 6. Event Model

`task.*` / `delegation.*` / `agent.*`；含 `event_id`（幂等）、`root_task_id`、`correlation_id`、`payload`。有序：按插入顺序；可按 task/root 查询。

---

## 7. Retry / Recovery

- Backoff：`base * 2^attempt`（封顶）
- 同 `root_task_id` / `correlation_id` / `task_id` / `a2a-del-*`
- `apply_callback`：迟到 callback 不改写 terminal
- `recover`：`UNKNOWN|RUNNING|RECOVERABLE|TERMINAL`；ownership 互斥

---

## 8. Agent Lifecycle

heartbeat 自动 READY/BUSY；drain 后拒绝新任务；`active_tasks==0` → OFFLINE。

---

## 9. Governance 变化

- **未重写** Phase 2 `check/release`
- check 通过后增加 lifecycle/capacity 门禁
- denial → `a2a_governance_*` metrics
- PolicyEngine 合并 governance 行 + overrides（`max_retries` / timeouts / allow|deny lists）

---

## 10. Observability

- Metrics：`a2a_tasks_*` / `a2a_delegations_*` / `a2a_governance_*`（prometheus_client）
- Trace：复用 OTel
- Logs：execution 模块 `logging` structured messages

---

## 11. Collaboration Graph

- Edge 增列：`delegation_id/attempt/started_at/finished_at/duration_ms/error`
- `update_edge_status` 支持结束态
- Graph 节点可附带 `state/active_tasks/last_seen`
- 仍允许 `A→B→A`；visit count 由 Phase 2 `branch_lineage` 负责

---

## 12. 测试结果

| Suite | Result |
|-------|--------|
| Phase 3 state/service/lifecycle/reliability | **29 passed** |
| agent-runtime (Phase 2 hermetic) | **65 passed** |
| a2a-sdk | **8 passed** |
| start-agent | **5 passed** |

---

## 13. Phase 2 回归

- `delegate()` / governance check / visited_agents / idempotency / collaboration graph：**保持兼容**
- Legacy 未登记 Agent：lifecycle 不阻断
- Phase 2 API 未删除

---

## 14. 已知限制

1. Execution Record / Lifecycle **默认内存**；生产需跑 `020_*.sql` 并用 `PostgresExecutionRecordStore`（类已提供，服务默认内存便于 hermetic）。
2. Gateway 上 `/v1/agents/{id}/health` 与 registry 的 `POST .../health` 并存；经 Gateway 请用 `/v1/agent-runtime/{id}/*`。
3. Cancel 级联覆盖 **execution records**；向下游 Agent 推送 A2A `tasks/cancel` 仍依赖既有 agent 能力，未做全图 HTTP fan-out。
4. Trace 跨进程 agent↔agent span 属性约定已具备字段，未强制改动所有 Agent 埋点。
5. Capacity `wait` 策略仅 policy 字段预留，当前门禁为 reject。

---

## 15. Phase 4 建议

1. 默认切换 Postgres ExecutionRecord + 事件落库
2. Collaboration graph WebSocket 实时推送
3. Cancel 沿 runtime edges 向子 Agent fan-out
4. Router v3 CandidateFilter 接入 lifecycle+capacity 评分
5. Chaos 套件接入 CI（crash / late callback / concurrent recover）

---

## 旧能力 → 复用 / 新能力 → 位置

| 旧能力 | Phase 3 |
|--------|---------|
| Governance check/release | 复用 + lifecycle 门禁 |
| Runtime graph / visited_agents | 复用 + edge 时序字段 |
| a2a-del-* 幂等 | 复用，写入 Execution Record |
| Prometheus / OTel | 扩展 a2a_*，不另起炉灶 |
| `POST /v1/tasks/{id}/cancel` | 扩展 cascade |
| request_tracking | 并存；Execution Record 为新 SoT |

| 新能力 | 位置 |
|--------|------|
| State machines | `execution/state_machine.py` |
| Execution Record | `execution/record.py` + `service.py` |
| Events | `execution/events.py` |
| Recover / Retry / Timeout | `execution/service.py` + `retry.py` |
| Agent Lifecycle | `agent_lifecycle/` |
| Policy | `execution/policy.py` |
| a2a metrics | `observability/a2a_metrics.py` |

---

## Phase 3 PASS / FAIL

**Phase 3 PASS**
