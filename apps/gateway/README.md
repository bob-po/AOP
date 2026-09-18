# AOP Gateway (Go)

Phase 2: Agent Registry API.

## Run

```bash
cd apps/gateway
go mod tidy
go run ./cmd
```

Default listen: `:8080`

Env:

| Variable | Default |
|----------|---------|
| `GATEWAY_ADDR` | `:8080` |
| `DATABASE_URL` | `postgres://aop:aop@127.0.0.1:5432/aop?sslmode=disable` |
| `REDIS_ADDR` | `127.0.0.1:6379` |
| `DEFAULT_TENANT_ID` | `00000000-0000-0000-0000-000000000001` |

## APIs

```
POST /v1/agents/register   {"endpoint":"http://127.0.0.1:8001"}
GET  /v1/agents?skill=web-search&status=online
GET  /v1/agents/{id}
POST /v1/agents/{id}/disable
POST /v1/agents/{id}/enable
POST /v1/agents/{id}/health
DELETE /v1/agents/{id}
```
