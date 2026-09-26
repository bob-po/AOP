# Harness Migration

## Split of concerns

| Layer | Owns | Code |
|-------|------|------|
| **A2A OS** | How agents collaborate (routing, scoring, lineage, cost, idempotency) | `apps/orchestrator`, `agent_runtime.collaboration` / `a2a_server` |
| **Harness** | How an agent finishes a task | `agent_runtime.harness` + runners |
| **Virtual agent** | One profile per harness product (agent-card + system prompt) | `agents/harness-agent/profiles/*` |

**Specialty agents and coder/researcher role splits are gone.** One agent per harness
product: `claude-code`, `deepseek-harness`, `pi`.

Virtual agent cards have **empty `skills`**. The planner writes `agent_key` into the plan node
`skill` field; the router resolves by agent_key.

## Architecture

```
A2A OS  --message/send-->  HarnessA2AAdapter  --run-->  Runner
                              | heartbeat
                              v
                     /v1/agent-runtime/{id}/heartbeat

Runners:
  ClaudeCliRunner       https://github.com/anthropics/claude-code
  DeepSeekHarnessRunner https://github.com/deepseek-ai/deepseek-harness
  PiCliRunner           https://github.com/earendil-works/pi
```

## Virtual cards

| Profile | Port | Notes |
|---------|------|--------|
| `claude-code` | 8011 | Claude Code Agent |
| `deepseek-harness` | 8012 | DeepSeek Harness Agent |
| `pi` | 8013 | Pi Agent |

Default planner: single node → `claude-code` (`DEFAULT_AGENT`). Override to route to another product.

When the goal asks for **all / every / 所有 / 全部 agents**, the planner fans out to
**one parallel node per ready online harness agent** (`method=heuristic_multi`).
Agents whose `/health` reports `runner_ready=false` (missing CLI / API key) are
**skipped** so the task can still complete on agents that work (usually Claude).

| Agent | Needs to be ready |
|-------|-------------------|
| `claude-code` | `claude` CLI on PATH (or `CLAUDE_CLI_PATH`) |
| `deepseek-harness` | `DEEPSEEK_API_KEY`（或 `OPENAI_API_KEY`）必填；可选 `DSH_HOME`（默认 `~/.aop/dsh-home`） |
| `pi` | `pi` CLI, **or** `PI_API_KEY` / `OPENAI_API_KEY` (tool_loop) |

## Environment

| Variable | Meaning |
|----------|---------|
| `HARNESS_PROFILE` | Profile dir name (default `claude-code`) |
| `HARNESS_RUNNER` | Override: `claude_cli` / `pi_cli` / `deepseek` |
| `HARNESS_ENABLED` | Default on in start script; `0` to skip |
| `HARNESS_PROFILES` | Comma filter, e.g. `claude-code,pi` |
| `DEFAULT_AGENT` | Planner target agent_key (default `claude-code`) |
| `CLAUDE_CLI_PATH` / `PI_CLI_PATH` / `DSH_CLI_PATH` | Binaries |
| `CLAUDE_CLI_PERMISSION_MODE` | Claude `-p` permission mode (default `bypassPermissions`) |
| `CLAUDE_CLI_ALLOWED_TOOLS` | Comma list for `--allowed-tools` (default includes WebSearch/WebFetch); `none` to omit |
| `A2A_OS_URL` / `GATEWAY_URL` | Heartbeat + optional cost POST |

## Remote install (Claude Code–style)

```powershell
irm http://<a2a-os>:8000/install/claude-code.ps1 | iex
```

```bash
curl -fsSL http://<a2a-os>:8000/install/claude-code.sh | bash
```

## Local run

```powershell
pip install -e "packages/agent-runtime[harness]"
pip install -e packages/a2a-sdk
python scripts/start_and_register_agents.py
```

```powershell
$env:HARNESS_PROFILE="claude-code"; $env:PORT="8011"
uvicorn agent:app --app-dir agents/harness-agent --port 8011
```

## Async spawn（Agent 内委派）

父 Harness 可把耗时子目标交给另一个已注册 Agent，自己继续执行，稍后 join：

1. 子 Agent 的 `message/send` 在 `metadata.async=true` 或带 `callbackUrl` 时立即返回 `submitted`，后台跑 runner。
2. 父侧：`AgentCollaborator.spawn` / `join`，或 HTTP `POST /v1/collab/spawn` 与 `/v1/collab/join`。
3. Lineage 与 runtime edges 仍走现有 A2A OS 路径。

## Platform async（编排 Worker）

默认开启（`A2A_EXEC_ASYNC=1`）：Worker 对 Agent 使用 `async_mode` 提交后**立刻 ACK Redis 消息**，在线程池中 `tasks/get` join，再 `mark_success` 解锁下游。这样长跑节点不再占满单个 consumer。

| 变量 | 默认 | 含义 |
|------|------|------|
| `A2A_EXEC_ASYNC` | `1` | `0` 恢复同步阻塞执行 |
| `A2A_ASYNC_WORKERS` | `8` | join 线程池大小 |
| `A2A_ASYNC_JOIN_TIMEOUT` | `A2A_TIMEOUT` 或 `900` | join 最长等待（秒） |
| `A2A_ASYNC_POLL_INTERVAL` | `2` | poll 间隔（秒） |

不支持 async 的旧 Agent 会忽略 flag 并同步跑完；Worker 见 `completed` 后仍走原 finalize 路径。
