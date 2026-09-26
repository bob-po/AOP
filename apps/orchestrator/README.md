# Orchestrator (Python)

## Phase 1–4

见前文：Executor / Router / Planner / Scheduler / Streams Worker / Aggregator

## Phase 5 — Artifacts (MinIO)

- `artifacts/` — 上传/下载/列表
- 路径：`s3://aop-artifacts/tasks/{task_id}/{node}/{name}`
- Worker 写入 `output.md` / `output.json` / `meta.json`，URI 写入 node `output_json.artifacts`
- 下游节点优先从 MinIO 读取上游 `output.md`（兼容旧产物 `output.txt`）
- API：`GET /v1/tasks/{id}/artifacts`（经 Gateway 反代）

## Phase 7 — Workflows / Marketplace / Health

```bash
python scripts/phase7_workflow.py
python scripts/phase7b_marketplace.py

# optional background health loop
python health_monitor.py --interval 30
```

Env：

| Variable | Default |
|----------|---------|
| `MINIO_ENDPOINT` | `127.0.0.1:9000` |
| `MINIO_ACCESS_KEY` | `aopminio` |
| `MINIO_SECRET_KEY` | `aopminio123` |
| `MINIO_BUCKET` | `aop-artifacts` |
| `GATEWAY_URL` | `http://127.0.0.1:8080` |
| `HEALTH_INTERVAL` | `30` |
