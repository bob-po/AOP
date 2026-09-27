# Agent 开发规范

> 完整平台设计见 [技术方案](./A2A-Agent-调度平台-v1.0-技术方案.md)  
> 协议基线见 [a2a-protocol.md](./a2a-protocol.md)（对齐 [a2aproject/A2A](https://github.com/a2aproject/A2A)）

## 最小交付物

每个 Agent 目录必须包含：

```
agents/<name>/
├── Dockerfile
├── agent.py          # 或等价入口
├── agent-card.json   # Agent Card
├── requirements.txt
└── README.md         # 输入/输出/依赖
```

## 合规 Agent Card

必填：

- `name` / `description` / `url` / `version`
- `protocolVersion`：`0.3.0`（与平台钉扎的官方 spec 一致）
- `preferredTransport`：建议 `JSONRPC`
- `skills[]`（含 `id` / `name` / `description`）；无 skills 的透传 harness 可为空数组
- `capabilities`：必须**诚实**声明 `streaming` / `pushNotifications`

推荐：

- `defaultInputModes` / `defaultOutputModes`
- `securitySchemes` / `security`（无认证可为空）
- `extensions`：平台扩展声明（可选）

Wire 约定：

- Message parts 使用官方判别字段 **`kind`**（`text` / `data` / `file`）；平台仍可读旧字段 `type`
- 平台治理字段（`correlationId`、`visitedAgents`、…）放在 `metadata`；勿发明新的顶层 RPC
- 长任务：`message/send` 可先返回 `submitted`，客户端用 `tasks/get` 轮询；支持流式则实现 `message/stream`（SSE）

## 生命周期

```
启动 → POST /v1/agents/register →（可选）周期性 health
     → 接收 A2A message/send 或 message/stream → 返回 Artifact
```

平台侧还会：

- 写入 `agent_runs`（延迟 / 成败）供智能路由评分
- 节点成功后写入 `task_memories` 的 `node:{key}` 摘要
- 若 skill ∈ `HITL_SKILLS`，节点进入 `waiting_for_user`，等待 Console 批准

## 约束

- 对外只暴露 A2A 接口；内部技术栈自定
- OS 控制面（注册 / 路由 / DAG / HITL）走 `/v1/*`，不是 A2A 方法
- 不假设可访问平台数据库
- 产物可返回内联 Text/JSON；平台会落盘 MinIO
- Code / Browser / RPA 类 Agent 必须容器隔离（见 [agent-sandbox.md](./agent-sandbox.md)）
- 本地开发时 Docker 主机名在 `AOP_RUNTIME=host` 时会被 Router 映射为 `127.0.0.1:端口`
- 废弃（仍可读，勿新写）：`tasks/delegate`、Part 仅写 `type`、governance 顶层字段（请用 `metadata`）

## 已落地 Agents（harness profiles）

专项 Agent 已下线。仅保留 [`agents/harness-agent`](../../agents/harness-agent/)；每个 profile 是一个虚拟 Agent（含 openclaw / hermes）。

详见 [harness-migration.md](./harness-migration.md)。

一键启动并注册：

```bash
python scripts/start_and_register_agents.py
```
