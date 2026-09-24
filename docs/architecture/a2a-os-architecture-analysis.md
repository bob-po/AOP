# A2A OS 架构分析报告

> **状态：** 演进分析快照（对照「旧编排器」与目标 OS）。现行落地以 [overview.md](./overview.md) 与 [Phase 3–6 交付](../phases/phase-03/delivery-report.md) 为准；下文「当前架构」描述的是改造前基线。

## 1. 基线架构 (BASELINE — 改造前)

### 1.1 整体结构
```
User → Gateway → Orchestrator → Planner → Router → Scheduler → Executor → Agent
```

- **Gateway (Go)**: 负责认证、API Key、RBAC、审计、代理到 Orchestrator。暴露 `/v1/agents/register` 等控制平面 API。
- **Orchestrator (Python)**: 核心业务逻辑，包括 Planner、Router、Scheduler、Executor。
- **Planner**: 将用户目标分解为 DAG（有向无环图）。
- **Router**: 根据技能匹配选择 Agent。
- **Scheduler**: 管理任务状态和节点依赖。
- **Executor**: 调用 Agent 执行任务。
- **Agent**: 纯 Server，接收 JSON-RPC `message/send` 调用。

### 1.2 关键组件分析

#### 1.2.1 Orchestrator Call Flow
- **入口**: `POST /v1/tasks` → `TaskService.create()` → `TaskManager.create()` → `PlanningEngine.plan()` → `SchedulingEngine.create_and_enqueue()`
- **执行**: Worker 从 Redis Stream 读取任务 → `ExecutionEngine.handle()` → `RoutingEngine.select()` → `A2AExecutor.execute()` → 直接调用 Agent
- **Planner**: 动态 DAG，支持关键词分解和 LLM 规划
- **Router**: 仅在 Orchestrator 内部调用，无 HTTP 路由端点
- **Scheduler**: 管理节点状态和依赖，不决定调用哪个 Agent
- **Executor**: 唯一的 A2A Client，调用 Agent 的 JSON-RPC 接口

#### 1.2.2 A2A SDK
- `A2AClient` 仅支持 `message/send` 和 `tasks/get`
- 无 streaming、callback、delegation、`correlation_id`、`parent_task_id`、`root_task_id`
- Agent 不使用 SDK，纯 Server

#### 1.2.3 Agent 能力
- 所有 9 个 Python Agent 都是 Server-only
- 无 outbound A2A 调用能力
- 依赖 Orchestrator 组合上游结果

#### 1.2.4 Router v3
- 公开 API: `GET /v1/router/preview?skill=...`
- 实际 pipeline: Skill Match → Health Filter → Scoring → Selection
- Capability/IO/Resource/Tenant Filter 未集成（死代码）
- Failover 在 Executor 中实现

#### 1.2.5 Task/Message 模型
- Task 模型扁平，无 `parent_task_id`、`root_task_id`、`correlation_id`
- 无 Session/Context 跨 Agent 传播
- 事件仅通过 `task_id` 关联

#### 1.2.6 基础设施
- Registry: PostgreSQL + Redis，由 Gateway 管理
- Auth: 仅在 Gateway 层，Agent 间无认证
- Agent 直接调用，不经过 Gateway

### 1.3 架构偏差总结
- **中心化编排**: 所有 Agent 调用必须经过 Orchestrator
- **无 Agent 间直接通信**: Agent 无法自主发现和调用其他 Agent
- **无任务图**: Task 模型不支持父子任务关系
- **Router 不可被 Agent 调用**: 仅 Orchestrator 内部使用

## 2. 目标架构 (TARGET ARCHITECTURE)

```
                ┌──────────────────┐
                │     A2A OS       │
                │                  │
                │ Agent Registry   │
                │ Discovery        │
                │ Router           │
                │ Auth             │
                │ Message Bus      │
                │ Task Runtime     │
                │ Governance       │
                └────────┬─────────┘
                         │
      ┌──────────────────┼──────────────────┐
      │                  │                  │
      ▼                  ▼                  ▼
 Research Agent     Analysis Agent      RAG Agent
      │                  │                  │
      │ A2A Call        │ A2A Call        │
      └──────────────────┘                  │
                ▲                           │
                └───────────────────────────┘
```

### 2.1 核心变化
- **Agent 一等公民**: Agent 同时是 Server 和 Client
- **去中心化协作**: Agent 可直接调用其他 Agent
- **动态委托**: Agent 可在运行时发现和调用其他 Agent
- **Router 开放**: Agent 可调用 Router 进行发现和路由
- **任务图支持**: Task 模型支持父子任务关系
- **双向通信**: 支持 Agent 间双向调用

### 2.2 核心组件
- **Identity**: Agent ID、Card、认证、API Key
- **Discovery**: Agent 注册、搜索、能力发现
- **Routing**: 技能匹配、能力匹配、兼容性检查
- **Communication**: A2A 消息、任务、事件、流式传输
- **Runtime**: 执行、超时、重试、取消、并发
- **Governance**: 权限、配额、预算、速率限制、审计
- **可选协调**: 规划、工作流、DAG（Orchestrator 降级为可选）

## 3. 架构差距 (ARCHITECTURE GAP)

### 3.1 核心差距
1. **Agent 无 Client 能力**: 所有 Agent 都是 Server-only，无法发起 A2A 调用
2. **Task 模型不支持委托**: 无 `parent_task_id`、`root_task_id`、`correlation_id`
3. **Router 不可被 Agent 调用**: 仅 Orchestrator 内部使用
4. **无 Session/Context 传播**: 跨 Agent 调用无上下文传递
5. **无任务图查询**: 无 `GET /v1/runtime/graph/{root_task_id}`
6. **无 delegation API**: 无 `POST /v1/tasks/{id}/delegate`
7. **无治理机制**: 无递归深度限制、循环检测、配额控制

### 3.2 具体缺失组件
- `A2AClient` 扩展（streaming、cancel、delegate）
- Task 模型字段扩展（`parent_task_id`、`root_task_id`、`correlation_id`、`caller_agent_id`、`target_agent_id`、`depth`）
- Agent Runtime（生命周期、上下文传播、委托）
- Router 开放 API（`POST /v1/route`、`POST /v1/discover`）
- 治理错误类型（`RECURSION_LIMIT_EXCEEDED`、`CYCLE_DETECTED`、`QUOTA_EXCEEDED`）

## 4. 迁移计划 (MIGRATION PLAN)

### 4.1 第一阶段：基础架构改造
1. **扩展 A2A SDK**
   - 添加 streaming、cancel、delegate 方法
   - 添加 `correlation_id`、`parent_task_id`、`root_task_id` 支持
   - 添加治理错误类型

2. **扩展 Task 模型**
   - 添加 `parent_task_id`、`root_task_id`、`correlation_id`、`caller_agent_id`、`target_agent_id`、`depth`
   - 添加 `timeout`、`ttl`、`callback_url` 字段

3. **实现 Agent Runtime**
   - 创建 `AgentRuntime` 类，支持生命周期管理
   - 实现上下文传播和委托功能
   - 添加递归深度限制和循环检测

4. **开放 Router API**
   - 添加 `POST /v1/route` 和 `POST /v1/discover` 端点
   - 允许 Agent 直接调用 Router

### 4.2 第二阶段：Agent 改造
1. **为 Agent 添加 Client 能力**
   - 在 Agent 中集成 `A2AClient`
   - 实现 `discover` 和 `route` 方法
   - 支持委托逻辑

2. **实现动态委托**
   - 在 Agent 中添加能力检测和委托逻辑
   - 支持运行时发现和调用其他 Agent

3. **测试 Agent 间调用**
   - 实现 Test 1: Agent A → Agent B
   - 实现 Test 2: Agent A → Agent B → Agent C
   - 实现 Test 3: Agent A → Agent B → Agent A
   - 实现 Test 4: Agent A → Agent B 和 Agent A → Agent C
   - 实现 Test 5: Agent B 自主发现和调用 Agent C

### 4.3 第三阶段：治理和监控
1. **实现治理机制**
   - 添加递归深度限制
   - 添加循环检测
   - 添加配额控制
   - 添加审计日志

2. **实现运行时图查询**
   - 添加 `GET /v1/runtime/graph/{root_task_id}` 端点
   - 支持任务图的可视化和查询

3. **集成测试**
   - 验证所有测试用例通过
   - 确保现有功能不受影响

### 4.4 第四阶段：文档和培训
1. **更新文档**
   - 更新 API 文档
   - 更新 Agent 开发规范
   - 添加 A2A OS 架构说明

2. **培训团队**
   - 培训开发团队理解新架构
   - 提供最佳实践指南

## 5. 结论

当前系统存在明显的中心化编排偏差，所有 Agent 调用必须经过 Orchestrator。目标架构要求 Agent 成为自主的协作实体，能够直接发现和调用其他 Agent。迁移计划分为四个阶段，逐步实现基础架构改造、Agent 改造、治理机制和文档更新。通过增量迁移，确保现有功能不受影响，同时实现 A2A OS 的核心目标。

---

## 6. 实施进度 (IMPLEMENTATION STATUS)

> 定位更新：本系统是 **A2A Operating System — Runtime infrastructure for autonomous Agent-to-Agent collaboration**，不是 Multi-Agent Workflow Orchestrator。Orchestrator 保留为可选的 Coordination Agent。

### 6.1 已完成（增量迁移，未破坏既有功能）

| 模块 | 交付内容 | 关键文件 |
|------|----------|----------|
| A2A SDK 扩展 | streaming / cancel / delegate；`correlation_id`/`parent_task_id`/`root_task_id`/`depth`/`caller_agent_id`/`target_agent_id` 全链路 | `packages/a2a-sdk/a2a_sdk/{client,models}.py` |
| 开放 Router/Discovery | `POST /v1/route`、`POST /v1/discover`，复用 Router v3 全流程并接入此前为死代码的 `CandidateFilter`（capability/IO/health/resource/tenant/policy） | `apps/orchestrator/router/__init__.py`（`discover`/`route`）、`main.py` |
| Agent 侧协作运行时 | `A2ACollaborationRuntime`：discover→route→delegate，lineage 传播 + 治理（max depth / call limit / 环检测，允许 A→B→A） | `packages/agent-runtime/agent_runtime/collaboration.py` |
| Agent Server 复用件 | 入站 lineage 解析、JSON-RPC 结果/错误、`tasks/cancel` | `packages/agent-runtime/agent_runtime/a2a_server.py` |
| 运行时调用图 | `a2a_runtime_edges` 表 + `POST /v1/runtime/edges` + `GET /v1/runtime/graph/{root_task_id}`（运行时执行图，**非**预定义 DAG） | `infrastructure/postgres/init/018_a2a_runtime_graph.sql`、`apps/orchestrator/runtime_graph/` |
| Gateway 开放 | `/v1/route`、`/v1/discover`、`/v1/runtime/*` 代理放行（任意已鉴权 Agent 可直连） | `apps/gateway/internal/httpapi/server.go` |
| Agent 一等公民（样板） | analysis-agent 改造为 Server+Client：解析入站 lineage、自主 Discovery 并委托 RAG 同级 Agent、`tasks/cancel`；默认无 OS 时安全降级 | `agents/analysis-agent/{agent,collab}.py` |
| Agent 一等公民（全量） | 其余 8 个 Agent（search/rag/report/image/video/code/browser/ppt）统一接入共享 `AgentCollaborator`：message/send 解析入站 lineage + 可选自主委托 + `tasks/cancel`；无 OS URL 时委托默认关闭、既有行为不变；各配 `tests/test_a2a_server.py`（4 用例/个） | `agents/*/agent.py`、`packages/agent-runtime/agent_runtime/agent_collab.py` |
| 验收测试 | Test1 A→B、Test3 A→B→A、Test4 扇出、Test5 闭环 A→B→C→B→A（自主发现，无中心编排）、治理阻断失控递归 | `packages/agent-runtime/tests/test_a2a_closed_loop.py` |
| 现场验收脚本 | `python scripts/a2a_os_closed_loop.py` 对真实服务演示 discover/route/runtime-graph | `scripts/a2a_os_closed_loop.py` |
| **委托 lineage 修正** | `CallContext.self_task_id`（由 `from_inbound` 从入站 task_id 填充）；`delegate()` 以 `self_task_id` 作为子边 `parent_task_id`，使真实多跳链在运行时图中正确嵌套（caller task → callee task） | `packages/agent-runtime/agent_runtime/collaboration.py` |
| **真实跨进程自主闭环** | `scripts/a2a_autonomous_demo.py`：直接向 search-agent 提交（**绕过 orchestrator**），Agent 自主 discover→delegate 形成 Research→Analysis→RAG，边由 Agent 自行上报，再从 Postgres 读回真实运行时图并断言嵌套（**非模拟**） | `scripts/a2a_autonomous_demo.py` |
| **实时验收测试（真实传输）** | Test1 基础调用、Test3 动态选择、Test2+Test6 自主多跳且无中心编排——全部经真实 HTTP A2A 打到独立 Agent 进程；OS 不可达时整模块 skip | `packages/agent-runtime/tests/test_a2a_live_integration.py` |
| **最小 CLI** | `aop agent list/discover`、`aop task submit/inspect`、`aop runtime graph`（HTTP 包装 OS 与 Agent，无新 Console/UI） | `scripts/aop.py` |

测试结果：a2a-sdk 5、agent-runtime 54（含 3 个实时集成用例 + 闭环 + 治理）、analysis-agent 7、rag-agent 6、8 个改造 Agent 各 4、orchestrator router discovery 8 全绿；gateway `go build` 通过；orchestrator `main`/`router`/`runtime_graph`/`task_service` 导入通过。

**Phase 1 自主协作闭环已实测通过**（真实进程、真实 A2A HTTP、无中心编排）：

```
search-agent → analysis-agent  [skill=business-analysis depth=1 completed]
  analysis-agent → rag-agent   [skill=knowledge-search  depth=2 completed]
```

验收场景映射：Test1（live）、Test2（live，自主多跳）、Test3（live，Discovery+Router 动态选择）、Test4（hermetic，A→B→A 合法 + 失控环阻断）、Test5（hermetic，max depth / call limit 阻断）、Test6（live，直连 Agent 绕过 orchestrator）。

### 6.2 Phase 2 状态（跨进程协作治理与可靠任务运行时）

| 优先级 | 能力 | 状态 | 要点 |
|--------|------|------|------|
| P0 | 跨进程 `visited_agents` | ✅ | 链上累积、分支隔离；允许 A→B→A，用 `max_agent_visits` 阻断无限环（非“出现过即禁”） |
| P0 | OS quota/budget/call limit | ✅ | `delegate()` 调用 `POST /v1/governance/check|release`；DB/Redis 原子计数；拒绝写入 `a2a_governance_denials` |
| P1 | Duplicate / 幂等 | ✅ | 委托稳定键 `a2a-del-*`；Agent 侧缓存 + Orchestrator `request_tracking` |
| P1 | subscribe + callback | ✅ | `tasks/subscribe`；SDK `callbackUrl`；`notify_callback` |
| P1 | Task ↔ Runtime Graph | ✅ | Executor 播种 `root_task_id`；`GET /v1/tasks/{id}/collaboration-graph` |
| P2 | 10/10 Client 化 | ✅ | start-agent A2A FastAPI 门面（DeployPilot 仍为引擎） |
| P2 | Collaboration Graph API | ✅ | `nodes`/`links`/`tree`；Gateway `/v1/collaboration/*` |

### 6.3 架构原则落点

- **OS Governs, Agents Decide**：`/v1/route`、`/v1/discover` 只返回候选与建议，调用与否由 Agent 决定；治理限额由 OS 权威判定，Agent 不可自抬。
- **Optional Orchestration**：Orchestrator 不再是 Agent 协作必经节点；Agent 可经 OS 基础设施直接互调。
- **Runtime ≠ Workflow**：`a2a_runtime_edges` 记录的是实际发生的调用边（runtime execution graph），与 `task_dependencies`（预定义 DAG）明确区分。
- **Limited revisits**：治理比较的是分支上的访问次数，不是全局黑名单——合法回访与失控循环被明确区分。

### 6.4 Phase 3 状态（可靠执行 + 可观测 + 生命周期）

详见 `docs/phases/phase-03/delivery-report.md`。摘要：

| 能力 | 状态 |
|------|------|
| Execution / Agent 状态机 + terminal 保护 | ✅ |
| Execution Record SoT + recover/cancel cascade | ✅ |
| Retry / Timeout / late-callback 保护 | ✅ |
| Execution Events + a2a_* Metrics | ✅ |
| Agent Lifecycle（READY/BUSY/DRAINING）+ heartbeat | ✅ |
| PolicyEngine + capacity 门禁（复用 Governance） | ✅ |
| Phase 2 hermetic 回归（65+） | ✅ |
