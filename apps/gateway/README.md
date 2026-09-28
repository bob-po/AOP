# AOP Gateway (Go)

注册中心 · 鉴权 / RBAC · 反向代理到 Orchestrator。默认监听 `:8080`。

## Run

```bash
cd apps/gateway
go mod tidy
# PowerShell: $env:ORCHESTRATOR_URL="http://127.0.0.1:8090"
go run ./cmd
```

| 变量 | 默认 |
|------|------|
| `GATEWAY_ADDR` | `:8080` |
| `DATABASE_URL` | `postgres://aop:aop@127.0.0.1:5432/aop?sslmode=disable` |
| `REDIS_ADDR` | `127.0.0.1:6379` |
| `ORCHESTRATOR_URL` | `http://127.0.0.1:8090` |
| `AUTH_REQUIRED` | 本地 `false`，部署 `true` |

## 主要 API

```text
POST /v1/agents/register   {"endpoint":"http://127.0.0.1:8011"}
GET  /v1/agents
GET  /v1/agents/{id}/health
POST /v1/auth/login · GET /v1/auth/me
# 其余任务 / 计费 / 市场等反代到 Orchestrator
```

注册时拉取 Agent Card：`/.well-known/agent-card.json`（兼容 `agent.json`）。  
完整契约见 [docs/reference/api.md](../../docs/reference/api.md)。启动全栈见 [getting-started](../../docs/guides/getting-started.md)。
