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

## 远端安装（Marketplace）

A2A OS 可达时（示例口 `:8000` 或 Gateway `:8080`，以实际 Marketplace 为准）：

```powershell
irm http://<a2a-os>/install/claude-code.ps1 | iex
```

## 边缘节点

也可用 [`apps/client/aop-node`](../../apps/client/aop-node) 以 Windows 服务拉起本机 plugins/harness。

完整说明：[harness-migration.md](../../docs/architecture/harness-migration.md) · [a2a-protocol.md](../../docs/architecture/a2a-protocol.md)。
