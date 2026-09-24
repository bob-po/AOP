# A2A 协议落地说明

> 完整平台设计见 [技术方案](./A2A-Agent-调度平台-v1.0-技术方案.md)  
> 状态：已支撑 Phase 1–12 异步 DAG 执行、HITL、智能路由

## 已冻结决策

| 项 | 约定 |
|----|------|
| 规范基线 | A2A-compatible subset，对齐 **protocolVersion `0.3.0`** 能力模型 |
| Agent Card 发现 | 优先 `GET /.well-known/agent-card.json`；兼容 `/.well-known/agent.json` |
| 调用传输 | JSON-RPC 2.0，`POST {agent.url}` |
| 首批方法 | `message/send`、`tasks/get` |
| Auth | 默认 `none`；`agent_endpoints.auth_type` 可扩展 |
| SDK 包 | `packages/a2a-sdk`（`aop-a2a-sdk`） |
| 超时 | `A2A_TIMEOUT`（Worker 默认 60s） |

## 要点

1. **A2A 是通信协议，不是 Google API 绑定。** 自研与第三方 Agent 均可接入。
2. 平台侧统一通过 `packages/a2a-sdk` 访问 Agent，禁止在 Orchestrator 写死具体 Agent HTTP 细节。
3. 注册时拉取 **Agent Card**，解析 skills / endpoint / capabilities，写入 Registry + Redis Skill Set。
4. 执行路径：Scheduler 入队 → Worker 选 Agent（智能路由）→ `message/send` → Artifact 落 MinIO → 解锁下游。
5. HITL：部分 skill（`HITL_SKILLS`）节点成功后进入 `waiting_for_user`，不立即解锁下游。

## 状态映射

| A2A Task state | 平台 Node status | 备注 |
|----------------|------------------|------|
| `submitted` / `working` | `running` | |
| `completed` | `success` 或 `waiting_for_user` | 若 `requires_approval` 则 HITL |
| `failed` | `failed` / `retrying` | Failover 同 skill 换 Agent |
| `canceled` | `cancelled` | |
| `input-required` | `waiting_for_user` | 平台侧用审批闸门近似 |

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

## 验收命令

```bash
# 单 Agent
cd agents/search-agent && uvicorn agent:app --port 8001
cd apps/orchestrator && python scripts/call_search_agent.py --query "A2A"

# 全套注册
python scripts/start_and_register_agents.py

# 智能路由预览
curl "http://127.0.0.1:8080/v1/router/preview?skill=web-search"
```
