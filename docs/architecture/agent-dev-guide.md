# Agent 开发规范

> 完整平台设计见 [技术方案](./A2A-Agent-调度平台-v1.0-技术方案.md)

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

## Agent Card 必填字段

- `name` / `description` / `url` / `version`
- `skills[]`（含 `id` / `name` / `description`）
- `capabilities`（至少声明是否 streaming）
- 建议 `protocolVersion` 与平台约定一致（`0.3.0`）

## 生命周期

```
启动 → POST /v1/agents/register →（可选）周期性 health
     → 接收 A2A message/send → 返回 Artifact
```

平台侧还会：

- 写入 `agent_runs`（延迟 / 成败）供智能路由评分
- 节点成功后写入 `task_memories` 的 `node:{key}` 摘要
- 若 skill ∈ `HITL_SKILLS`，节点进入 `waiting_for_user`，等待 Console 批准

## 约束

- 对外只暴露 A2A 接口；内部技术栈自定
- 不假设可访问平台数据库
- 产物可返回内联 Text/JSON；平台会落盘 MinIO
- Code / Browser / RPA 类 Agent 必须容器隔离（见 [agent-sandbox.md](./agent-sandbox.md)；Phase 27 已提供 seccomp + AST/egress 沙箱）
- 本地开发时 Docker 主机名（如 `claude-coder`）在 `AOP_RUNTIME=host` 时会被 Router 映射为 `127.0.0.1:端口`；Compose 内设 `AOP_RUNTIME=docker` 保留服务 DNS

## 已落地 Agents（harness × 角色）

专项 Agent（search/rag/report/…）已下线。仅保留 [`agents/harness-agent`](../../agents/harness-agent/)；每个 profile 是一个虚拟 Agent。

| Profile | Port | Skills | Harness |
|---------|------|--------|---------|
| claude-coder | 8011 | `code-execution`, `code-assist` | Claude Code CLI |
| claude-researcher | 8012 | `web-research`, `research-summarize`, `web-search` | Claude Code CLI |
| pi-coder | 8013 | `code-execution`, `code-assist` | Pi CLI |
| pi-researcher | 8014 | `web-research`, `research-summarize`, `web-search` | Pi CLI |
| deepseek-coder | 8015 | `code-execution`, `code-assist` | DeepSeek Harness |
| deepseek-researcher | 8016 | `web-research`, `research-summarize`, `web-search` | DeepSeek Harness |

详见 [harness-migration.md](./harness-migration.md)。

一键启动并注册：

```bash
python scripts/start_and_register_agents.py
```

远端主机（Claude Code 风格）：

```powershell
irm http://<a2a-os>:8000/install/claude-coder.ps1 | iex
```

Marketplace：`GET /v1/marketplace`（含 `install.windows` / `download`）。
