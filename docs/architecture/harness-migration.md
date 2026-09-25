# Harness Migration

## Split of concerns

| Layer | Owns | Code |
|-------|------|------|
| **A2A OS** | How agents collaborate (routing, scoring, lineage, cost, idempotency) | `apps/orchestrator`, `agent_runtime.collaboration` / `a2a_server` |
| **Harness** | How an agent finishes a task | `agent_runtime.harness` + runners |
| **Virtual agent** | Harness × role profile (agent-card + skills) | `agents/harness-agent/profiles/*` |

**Specialty agents under `agents/*` have been removed.** Only `agents/harness-agent` remains. There is no MCP down-shift of search/image/video — those agents are gone; researcher cards expose `web-search` as a skill alias for routing continuity.

## Architecture

```
A2A OS  --message/send-->  HarnessA2AAdapter  --run-->  Runner
                              | heartbeat
                              v
                     /v1/agent-runtime/{id}/heartbeat

Runners:
  ClaudeCliRunner       https://github.com/anthropics/claude-code
  PiCliRunner           https://github.com/earendil-works/pi
  DeepSeekHarnessRunner https://github.com/deepseek-ai/deepseek-harness
                        (SDK → dsh headless → DEEPSEEK_API_KEY tool_loop)
```

Output contract: artifact `summary` (text) + `result` (data with `skillId` / `schemaVersion` / `usage`).

## Virtual cards

| Profile | Port | Skills |
|---------|------|--------|
| `claude-coder` | 8011 | `code-execution`, `code-assist` |
| `claude-researcher` | 8012 | `web-research`, `research-summarize`, `web-search` |
| `pi-coder` | 8013 | `code-execution`, `code-assist` |
| `pi-researcher` | 8014 | `web-research`, `research-summarize`, `web-search` |
| `deepseek-coder` | 8015 | `code-execution`, `code-assist` |
| `deepseek-researcher` | 8016 | `web-research`, `research-summarize`, `web-search` |

## Environment

| Variable | Meaning |
|----------|---------|
| `HARNESS_PROFILE` | Profile dir name |
| `HARNESS_RUNNER` | Override: `claude_cli` / `pi_cli` / `deepseek` |
| `HARNESS_ENABLED` | Default on in start script; `0` to skip |
| `HARNESS_PROFILES` | Comma filter, e.g. `claude-coder,deepseek-coder` |
| `CLAUDE_CLI_PATH` / `PI_CLI_PATH` / `DSH_CLI_PATH` | Binaries |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | DeepSeek tool_loop |
| `A2A_OS_URL` / `GATEWAY_URL` | Heartbeat + optional cost POST |

## Remote install (Claude Code–style)

On another host, install a virtual agent the same way as Claude Code — one-liner pulls an installer that downloads the bundle, creates a venv, and drops a launcher under `~/.aop/`:

```powershell
# Windows (replace host with your A2A OS)
irm http://<a2a-os>:8000/v1/marketplace/agents/pkg-claude-coder/install.ps1 | iex

# Short alias
irm http://<a2a-os>:8000/install/claude-coder.ps1 | iex
```

```bash
# Linux / macOS
curl -fsSL http://<a2a-os>:8000/v1/marketplace/agents/pkg-claude-coder/install.sh | bash

# Short alias
curl -fsSL http://<a2a-os>:8000/install/claude-coder.sh | bash
```

Catalog entries expose the same commands under `install.windows` / `install.unix` (`GET /v1/marketplace/agents`). Zip-only download: `GET /v1/marketplace/agents/{package_id}/download`.

After install: ensure the harness binary (Claude / Pi / DeepSeek) is on PATH, edit `~/.aop/agents/<profile>/.env` so `AGENT_URL` is reachable from the OS, start the launcher, then `python scripts/register.py`.

## Local run

```powershell
pip install -e "packages/agent-runtime[harness]"
pip install -r agents/harness-agent/requirements.txt
python scripts/start_and_register_agents.py
```

Or single profile:

```powershell
$env:HARNESS_PROFILE="deepseek-coder"; $env:PORT="8015"
$env:DEEPSEEK_API_KEY="sk-..."
uvicorn agent:app --app-dir agents/harness-agent --port 8015
```

## Glue

- **Cancel chain**: `POST /v1/tasks/{id}/cancel` → `cancel_fanout` (+ running-node `extra_a2a_targets`) → agent `tasks/cancel` → harness `runner.cancel` (process tree kill / cancel flag) → A2A task `canceled`
  - OS cancel id matches agent `rootTaskId` / `correlationId` (and exact a2a id when known)
  - `A2AClient.cancel_task` accepts Task-shaped results (not only bool)
- Heartbeat → `POST /v1/agent-runtime/{id}/heartbeat`
- Cost → `metadata.usage` (`input_tokens` / `output_tokens` / `estimated_cost` / `wall_time_ms`)
- Events → `timestamp` + `payload.sequence`
