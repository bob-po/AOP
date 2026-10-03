# Chaos 恢复清单

本地跑任务时杀掉 Worker、Outbox 或 Orchestrator，应能在 Console 里把任务救回来。**不要改数据库。**

## 步骤

1. 打开 `http://127.0.0.1:3000`。顶栏预检变红时跟「故障恢复清单」进 **设置 → 监控**。
2. 重启被杀进程，或仓库根目录再跑 `python scripts/dev_up.py`。
3. 打开原任务（URL 带 `?task=`），点 **Retry**。卡在 `running` 占并发配额时同样 Retry 或 Cancel。

`GET /v1/preflight` 的 `recover_steps[].active` 对应当前阻塞项。Command Center 在 Worker/Outbox 未就绪时只显示激活步骤。

## 对照

| 杀谁 | 症状 | 进程 | Console |
|------|------|------|---------|
| Worker | 节点停 ready/running | `python worker.py` | Retry |
| Outbox | 新任务 ready、outbox pending | `python outbox_processor_service.py` | 自动投递或 Retry |
| Orchestrator | 502 / 预检失败 | `uvicorn main:app --port 8090` | 打开原任务 Retry |
| Gateway | 顶栏连不上 :8080 | `go run ./cmd` | 刷新 |
| 僵尸 running | 配额占满 | 不必改库 | Retry / Cancel |

详细排障见 [getting-started.md](../guides/getting-started.md) §7.17。
