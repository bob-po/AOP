# A2A 协议落地说明

> 完整平台设计见 [技术方案](./A2A-Agent-调度平台-v1.0-技术方案.md)  
> 官方规范：[a2aproject/A2A](https://github.com/a2aproject/A2A)

## 已冻结决策

| 项 | 约定 |
|----|------|
| 规范基线 | [a2aproject/A2A](https://github.com/a2aproject/A2A) `specification/a2a.proto`，钉扎 commit **`72b3761bd84c59291da694dcd97cdfc2c010df39`** |
| Card `protocolVersion` | **`0.3.0`**（与钉扎 spec 的 JSON 绑定一致） |
| Agent Card 发现 | 优先 `GET /.well-known/agent-card.json`；兼容 `/.well-known/agent.json` |
| 调用传输 | JSON-RPC 2.0，`POST {agent.url}`（preferredTransport=`JSONRPC`） |
| Part 判别 | 写出 **`kind`**；读入同时接受 `kind` \| `type`（不再 dual-write `type`） |
| 平台扩展 | 仅写在 `params.metadata` / `message.metadata`；读入仍接受顶层兼容字段 |
| SDK 包 | `packages/a2a-sdk`（`aop-a2a-sdk`） |
| 超时 | `A2A_TIMEOUT`（Worker 默认 60s） |

## 支持矩阵

| 方法 / 能力 | 级别 | AOP 状态 |
|-------------|------|----------|
| Agent Card well-known | Must | 支持 |
| `message/send` | Must | 支持 |
| `tasks/get` | Must | 支持 |
| `tasks/cancel` | Must | 支持 |
| `message/stream` (SSE) | Should | 支持（Harness）；Card `streaming` 须与实现一致 |
| Push (`pushNotificationConfig` / callback) | Later→partial | `metadata.pushNotificationConfig.url` + 兼容旧 `callbackUrl` |
| `tasks/resubscribe` | Later | 未实现 |
| `agent/getAuthenticatedExtendedCard` | Later | 未实现 |
| `tasks/subscribe` | Removed | SDK/服务端均返回 `-32601`；改用 `message/stream` |
| `tasks/delegate` | Removed | SDK/服务端均返回 `-32601`；改用 OS discover/route + `message/send` |

## 要点

1. **A2A 是通信协议，不是 Google API 绑定。** 自研与第三方 Agent 均可接入。
2. 平台侧统一通过 `packages/a2a-sdk` 访问 Agent，禁止在 Orchestrator 写死具体 Agent HTTP 细节。
3. 注册时拉取 **Agent Card**，解析 skills / endpoint / capabilities，写入 Registry + Redis Skill Set。
4. 执行路径：Scheduler 入队 → Worker 选 Agent → `message/send`（或 `message/stream`）→ Artifact 落 MinIO → 解锁下游。
5. HITL：部分 skill（`HITL_SKILLS`）节点成功后进入 `waiting_for_user`，不立即解锁下游。
6. **能力诚实**：未实现 SSE 的 Agent 不得宣称 `capabilities.streaming: true`。

## 状态映射

| A2A Task state | 平台 Node status | 备注 |
|----------------|------------------|------|
| `submitted` / `working` | `running` | |
| `completed` | `success` 或 `waiting_for_user` | 若 `requires_approval` 则 HITL |
| `failed` / `rejected` | `failed` / `retrying` | Failover 同 skill 换 Agent |
| `canceled` | `cancelled` | |
| `input-required` / `auth-required` | `waiting_for_user` | 平台侧用审批闸门近似 |

## 平台内部 DTO（与协议解耦）

```
InternalTaskNode
 ├── skill
 ├── requires_approval?
 ├── input / upstream artifacts
 ├── assigned_agent + score
 └── output_artifacts + memory summary
```

SDK 负责 Internal ↔ A2A 消息转换；规范升级时只改 SDK。

合规金样：`packages/a2a-sdk/tests/fixtures/`。

## 验收命令

```bash
# SDK compliance
pytest packages/a2a-sdk/tests -q

# 单虚拟 Agent（示例：claude-coder）
$env:HARNESS_PROFILE="claude-coder"; $env:PORT="8011"
uvicorn agent:app --app-dir agents/harness-agent --port 8011

# 全套注册
python scripts/start_and_register_agents.py
```
