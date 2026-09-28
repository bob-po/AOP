# Orchestrator (Python)

编排核心：Planner · Router · Scheduler · Execution · Worker · Outbox · Marketplace。

默认 API：`:8090`。

## 本地启动

```bash
cd apps/orchestrator
pip install -r requirements.txt
pip install -e ../../packages/a2a-sdk
uvicorn main:app --host 0.0.0.0 --port 8090

# 另开终端（必需）
python worker.py
python outbox_processor_service.py
```

| 变量 | 默认 |
|------|------|
| `DATABASE_URL` | `postgresql://aop:aop@127.0.0.1:5432/aop` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `MINIO_ENDPOINT` | `127.0.0.1:9000` |
| `GATEWAY_URL` | `http://127.0.0.1:8080` |
| `DEFAULT_AGENT` | `claude-code` |

> 不启动 Outbox 时，首批节点会卡在 `outbox_events(pending)`。

## 相关文档

- [启动指南](../../docs/guides/getting-started.md)
- [A2A 协议](../../docs/architecture/a2a-protocol.md)
- [Harness](../../docs/architecture/harness-migration.md)
- [Database](../../docs/reference/database.md) · [Redis](../../docs/reference/redis.md)
- 冒烟脚本：`scripts/phase*.py`
