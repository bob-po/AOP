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

## Environment

| Variable | Meaning |
|----------|---------|
| `HARNESS_PROFILE` | Profile dir name (default `claude-code`) |
| `HARNESS_RUNNER` | Override: `claude_cli` / `pi_cli` / `deepseek` |
| `HARNESS_ENABLED` | Default on in start script; `0` to skip |
| `HARNESS_PROFILES` | Comma filter, e.g. `claude-code,pi` |
| `DEFAULT_AGENT` | Planner target agent_key (default `claude-code`) |
| `CLAUDE_CLI_PATH` / `PI_CLI_PATH` / `DSH_CLI_PATH` | Binaries |
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
