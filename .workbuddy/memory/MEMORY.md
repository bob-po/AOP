# MEMORY.md — AOP 项目长期备忘

## 仓库定位
AOP = A2A OS（面向自主 Agent 协作的运行时基础设施），**不是** Multi-Agent Workflow Orchestrator。
Orchestrator 已降级为「可选的 Coordination Agent」。注意区分：
- `a2a_runtime_edges` = **运行时执行图**（真实发生的调用边）
- `task_dependencies` = **预定义 DAG**（Planner 产物）
两者不可混用。详见 `A2A-OS-ARCHITECTURE-ANALYSIS.md` 第 6 节。

## 前端（apps/web）约定
- 栈：Next.js 15 App Router + TS + Tailwind + reactflow 11 + recharts 3。**不新增 npm 依赖**。
- 唯一 API 出口：`lib/api.ts` 的 `request<T>()`。组件里禁止裸 fetch。
  降级通道：`requestOrchPreferred()` 在设了 `NEXT_PUBLIC_ORCHESTRATOR_BASE` 时直连 Orchestrator。
- WS 一律走 `hooks/useWebSocket.ts` 的 `buildWsUrl()`；禁止硬编码 `:8090`。
- 轮询：`useTaskLive` 为 WS 通 10s / 不通 2.5s。**不要新增高频轮询** —— 每次 poll 会经网关开多个 PG 连接，
  Windows 下会耗尽临时端口（见 `useTaskLive.ts` 内注释与 README 运维表）。
- 设计系统：ink-950/900/800/700、mist-100/200/400、signal(#3dffa8)/signal-dim/signal-warm(#ffb454)；
  font-display(Fraunces)/font-sans(Manrope)/font-mono(IBM Plex Mono)。
  微标签 `font-mono text-[10px] uppercase tracking-[0.18em] text-mist-400`；
  卡片 `rounded-2xl border border-white/10 bg-ink-900/50 p-4`。深色控制台风格，勿引入浅色面板。
- DAG / 图状态色统一参考 `components/tasks/TaskFlowDag.tsx` 的 `STATUS_COLOR`。
- 死代码（无任何 import，勿在此处投入改动）：`TaskMonitor.tsx`、`TaskWorkspace.tsx`、`TaskDag.tsx`、
  `SiteNav.tsx`、`AgentsPanel.tsx`、`WorkflowsPanel.tsx`、`MarketplacePanel.tsx`、`HomeComposer.tsx`。

## 网关（Go）路由所有权 —— 易踩坑
- `/v1/agents` 由 Gateway 自己的 registry handler 接管（`server.go` 中 `s.Agents.Routes(r)`）。
  因此 `GET /v1/agents/{id}/capacity` 与 `/reliability` **经网关不可达**（Orchestrator 有实现但被 registry 拦截）。
- 网关已放行到 Orchestrator 的 A2A OS 前缀：`/v1/route`、`/v1/discover`、`/v1/runtime/*`、`/v1/collaboration/*`、
  `/v1/governance/*`、`/v1/scheduling/*`、`/v1/tenants/*`、`/v1/agent-runtime/*`、`/v1/skills*`、
  `/v1/discover/skill`、`/v1/invoke/skill`。
- `/v1/agent-runtime/{id}/*` 是 Orchestrator 上的**安全别名**，只实现了 health / heartbeat / drain。

## 后端返回结构事实（易猜错）
- `ExecutionEvent` 字段名是 **`timestamp`**（不是 `ts`）；每 root 的 `sequence` 在 **`payload.sequence`**。
- `execution.store.classify()` → `{"class": <UNKNOWN|RUNNING|RECOVERABLE|TERMINAL>, "record": ...}`。
- `scheduling.cost.aggregate()` → `count / estimated_cost / input_tokens / output_tokens / gpu_seconds /
  wall_time_ms / currency` —— **没有** `tokens`、**没有** `trend`。
- `GET /v1/tenants/{id}/cost` 返回聚合 + `count`，**不含按天趋势**（趋势需另取 `/v1/billing/usage` 的 `daily_tasks`）。
- `GET /v1/collaboration/graph/{root}` 的 `nodes` 混两类：`type=agent`（id=agent_id，links 指向它）与
  `type=task`（id=`task:<task_id>`）；`links.source/target` 是 **agent_id**。
- `GET /v1/tasks/{id}` **总是**附带 `execution`；`?include_graph=true` 时附带 `collaboration_graph`/`runtime_graph`。
- 调度打分口径（UI 解释用）：
  `score = 0.25·capability + 0.15·availability + 0.20·reliability + 0.15·latency + 0.15·resource − 0.05·cost − 0.05·queue + 公平性微调`

## 运行/环境
- 本地默认 `AUTH_REQUIRED=false`；部署默认 `true`。会话存 `localStorage.aop_session_token`。
- 开发账号：`admin@aop.local` / `aop_admin_dev`（先跑 `infrastructure/postgres/migrate.py` + Phase 25 seed）。
- 新 SQL 迁移：Phase 3 = `020`，Phase 5 = `022–027`；改了网关需重新 `go run ./cmd` 才能代理新前缀。
