# Redis Streams 设计

> 配套文档：[技术方案主文档](./A2A-Agent-调度平台-v1.0-技术方案.md)  
> 实现：`apps/orchestrator/streams/__init__.py`

系统本质是**异步任务调度系统**。当前使用 **Redis Streams** 承载执行队列与事件。

## 1. Stream 清单（已用 / 规划）

| Stream | 状态 | 用途 | 生产者 | 消费者 |
|--------|------|------|--------|--------|
| `a2a.execution.queue` | ✅ | 就绪节点执行队列 | Scheduler / Worker(retry) | Worker (`cg-executor`) |
| `a2a.execution.events` | ✅ | 单次 Agent Run 事件 | Worker | 观测 / 调试 |
| `a2a.task.events` | ✅ | Task 生命周期事件 | Scheduler / Worker / Service | Trace 辅助 |
| `a2a.task.queue` | 规划 | 待规划任务 | Gateway | Planner |
| `a2a.agent.events` | 规划 | Agent 注册/上下线 | Registry | Monitor |
| `a2a.agent.heartbeat` | 规划 | Agent 心跳 | Agents | Health Monitor |
| `a2a.dlq` | 规划 | 死信 | Worker | 运维 |

**当前路径：** 创建 Task 时同步 Planner，直接把 READY 节点 `XADD` 到 `a2a.execution.queue`（不经独立 task.queue）。

## 2. 主事件流（落地）

```
User → POST /v1/tasks
 ↓
Planner（同步）+ Memory(goal)
 ↓
Scheduler：写 PG · READY 节点
 ↓
XADD a2a.execution.queue
 ↓
Worker (cg-executor)
 ├── Router.score(skill) → A2A → MinIO artifacts
 ├── agent_runs + Memory(node:*)
 ├── [HITL] → task/node waiting_for_user
 ├── unlock dependents → 再 XADD
 ├── stale reclaim（NODE_STALE_SECONDS）
 └── 终态 → Aggregator + Evaluation
 ↓
Console：WS（Pub/Sub）+ 轮询降级 GET /v1/tasks/{id}/events
```

关键事件类型（节选）：`task.created` · `task.node.ready` · `task.node.enqueued` · `agent.task.started` · `agent.task.completed` · `task.node.awaiting_approval` · `task.waiting_for_user` · `task.node.approved` · `task.completed` · `task.evaluated` · `task.node.stale_reclaimed`

## 3. 消息字段约定

### 3.1 Execution Queue（就绪节点）

```json
{
  "task_id": "…",
  "node_id": "…",
  "node_key": "search",
  "skill": "web-search",
  "attempt": "1",
  "exclude_agent_ids": "id1,id2"
}
```

字段以 Redis Stream string map 存储；延迟重试可由 Worker 等待后再 `XADD`。

### 3.2 Task / Execution Event

```json
{
  "event_type": "task.completed",
  "task_id": "…",
  "ts": "…",
  "payload": { }
}
```

权威 Trace 仍以 PostgreSQL `task_events` 为准；Stream 用于近实时辅助。

## 4. Consumer Group

| Group | Stream | 说明 |
|-------|--------|------|
| `cg-executor` | `a2a.execution.queue` | ✅ 多 Worker 竞争消费 + `XACK` |
| `cg-planner` 等 | 规划流 | 未单独拆分 |

**原则：** Consumer Group · 成功 `XACK` · 失败重试 / Failover（同 skill 排除已失败 agent）· 超 `max_retry` 标记 failed。

## 5. 辅助 Key 设计

| Key Pattern | 类型 | 状态 | 用途 |
|-------------|------|------|------|
| `agent:skill:{skill_id}` | Set | ✅ | skill → agent_id（Router） |
| `lock:task:{task_id}` | String + TTL | ✅ | DAG 推进分布式锁 |
| `task:{task_id}:state` | Hash | 可选 | 热状态缓存 |
| `agent:{agent_id}:state` | Hash | 可选 | online/load |
| `ws:task:{task_id}` | Pub/Sub | 未用 | 前端 WS（现为轮询） |

### Skill 索引

```
SADD agent:skill:web-search <agent_uuid>
```

注册 / 启用时维护；Router 先 Redis 再回源 PG。

## 6. 分布式锁

```
SET lock:task:{task_id} {worker_id} NX EX 30
```

Worker 在 `mark_success` / 解锁下游时持锁，防止重复派发。

## 7. 与 PostgreSQL 的分工

| 数据 | 存哪里 |
|------|--------|
| Agent、Task、DAG、Evaluation、Memory、审计 | PostgreSQL |
| 执行队列、Skill 索引、锁 | Redis |
| Trace 回放 | PG `task_events`（主）+ Stream（辅） |
| 路由评分样本 | PG `agent_runs` |

**写入顺序：** 先 PG 事务，再发 Redis 事件；消费者按 `task_id+node_key+attempt` 幂等。

## 8. docker-compose 参考（开发）

```yaml
redis:
  image: redis:7
  ports:
    - "6379:6379"
  command: ["redis-server", "--appendonly", "yes"]
```

生产建议监控 `XLEN a2a.execution.queue` 与 Consumer Pending。


## 9. Realtime Pub/Sub（Phase 14）

| Channel | 用途 |
|---------|------|
| `aop:task:{task_id}:events` | 单任务 WS 扇出（每连接完整副本） |
| `aop:events` | 全局系统事件 WS |

`publish_task_event` / `publish_execution_event` 在 `XADD` 后 `PUBLISH`；WebSocket 不再使用 competing consumer group。
