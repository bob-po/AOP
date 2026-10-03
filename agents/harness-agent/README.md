# Harness Agent — 唯一 A2A Agent 部署形态

专项 Agent（search/rag/report/…）与 coder/researcher 角色拆分已下线。  
本目录提供 **一个 harness 产品 = 一个虚拟 Agent**（`agent-card.json` + `system.md`）。

| Profile | Port | Runner |
|---------|------|--------|
| `claude-code` | 8011 | Claude Code CLI |
| `deepseek-harness` | 8012 | DeepSeek Harness |
| `pi` | 8013 | Pi CLI |
| `openclaw` | 8014 | OpenClaw |
| `hermes` | 8015 | Hermes |

Card 通常 **`skills: []`**（直通用户目标）；规划器默认打到 `claude-code`。

## 审批（随 `create_harness_app` 自带）

四种模式与互调信号写在 **[agent-approval.md](../../docs/architecture/agent-approval.md)**。本进程已提供：

```
POST /v1/approvals
GET  /v1/approvals?status=pending
POST /v1/approvals/{id}/decide
```

OS 在 `approval_mode=agent|both` 时把请求打到本 Agent；决定后回调 Gateway：

`POST /v1/tasks/{id}/approve` ，body 必须含 `"actor": "agent"`。

加新 profile **不必**再写审批代码；改 `profiles.py`、补 `profiles/<key>/`、设 `A2A_OS_URL`/`GATEWAY_URL` 即可。自研非 harness Agent 按该文档实现同一 HTTP 契约。

| 变量 | 默认 | 含义 |
|------|------|------|
| `HARNESS_APPROVAL_REVIEW` | 开 | `0` 只入队，不跑 runner 评审 |
| `A2A_OS_URL` / `GATEWAY_URL` | （空则无法回调） | 批准/驳回打到 OS |

## 本地 monorepo

```powershell
pip install -e "packages/agent-runtime[harness]"
pip install -e packages/a2a-sdk
pip install -r agents/harness-agent/requirements.txt
python scripts/start_and_register_agents.py
```

单 profile：

```powershell
$env:HARNESS_PROFILE="claude-code"; $env:PORT="8011"
uvicorn agent:app --app-dir agents/harness-agent --port 8011
```

推荐本机用仓库根目录 `python scripts/dev_up.py`（aop-node 拉起本进程）。Marketplace 安装脚本仍是 API，**Console 没有 Marketplace 页**（产品冻结）。

## 边缘节点

也可用 [`apps/client/aop-node`](../../apps/client/aop-node) 以 Windows 服务拉起本机 plugins/harness。

完整说明：[harness-migration.md](../../docs/architecture/harness-migration.md) · [agent-approval.md](../../docs/architecture/agent-approval.md) · [a2a-protocol.md](../../docs/architecture/a2a-protocol.md)。
