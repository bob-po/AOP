# aop-node plugins

Supervisor discovers `plugins/<id>/plugin.toml` and may autostart them.

## Ownership

| Concern | Owner when using aopd |
|---------|------------------------|
| Start / stop children | aop-node |
| `POST /v1/agents/register` | aop-node (node + each healthy child) |
| Lifecycle heartbeat | aop-node (`/v1/agent-runtime/{id}/heartbeat` for node + each harness) |
| A2A `message/send` | Child harness process |

Children set `AOP_NODE_MANAGED=1` / `HARNESS_HEARTBEAT=0` so they do **not** self-heartbeat.

Without aop-node, use `scripts/start_and_register_agents.py` (dev-only; each agent heartbeats itself).

## Layout

| Path | Role |
|------|------|
| `_harness/launch.py` | Shared launcher: find AOP repo → inject `PYTHONPATH` → uvicorn |
| `_harness/run_profile.py` | Shared plugin entry (marks node-managed) |
| `claude-code/` … `hermes/` | `plugin.toml` only (ports 8011–8015) |
| `echo/` | Smoke-test plugin (not an A2A agent) |

```text
plugins/<id>/
  plugin.toml   # id, port, HARNESS_PROFILE, args → ../_harness/run_profile.py
```

**Agent code is not vendored here.** Runtime lives in monorepo `agents/harness-agent` + `packages/agent-runtime`.

## Prerequisites

```powershell
pip install -e "packages/agent-runtime[harness]"
pip install -e packages/a2a-sdk
pip install -r agents/harness-agent/requirements.txt
```

| Profile | Needs |
|---------|--------|
| claude-code | `claude` on PATH |
| deepseek-harness | `DEEPSEEK_API_KEY` |
| pi | `pi` CLI or `PI_API_KEY` / `OPENAI_API_KEY` |
| openclaw | `openclaw` on PATH |
| hermes | `hermes` on PATH |

Optional: set `AOP_REPO_ROOT` if plugins are relocated outside the monorepo.

## Manual smoke (one agent, no aopd)

```powershell
cd apps\client\aop-node\plugins\claude-code
$env:HARNESS_PROFILE="claude-code"; $env:PORT="8011"; $env:AGENT_ID="claude-code"
$env:AOP_PLUGIN_DIR=(Resolve-Path .)
# launch.py (not run_profile.py) keeps self-heartbeat unless AOP_NODE_MANAGED=1
python -u ..\_harness\launch.py
# → http://127.0.0.1:8011/health
```

## Via aopd

```powershell
cd apps\client\aop-node
cargo run -p aopd -- --config aop-node.toml
# or Windows service: sc start aop-node
curl http://127.0.0.1:7920/v1/agents
curl http://127.0.0.1:7920/v1/agents/claude-code/start
```
