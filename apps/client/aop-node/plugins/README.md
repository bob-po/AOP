# aop-node plugins

Supervisor discovers `plugins/<id>/plugin.toml` and may autostart them.

## Layout

| Path | Role |
|------|------|
| `_harness/launch.py` | Shared launcher: find AOP repo → inject `PYTHONPATH` → uvicorn |
| `claude-code/` | Port **8011** · Claude Code CLI |
| `deepseek-harness/` | Port **8012** · DeepSeek Harness |
| `pi/` | Port **8013** · Pi CLI |
| `openclaw/` | Port **8014** · OpenClaw |
| `hermes/` | Port **8015** · Hermes |
| `echo/` | Smoke-test plugin (not an A2A agent) |

Each harness plugin is:

```text
plugins/<id>/
  plugin.toml   # Supervisor manifest
  run.py        # Sets profile env, calls _harness.launch
```

**Agent code is not vendored here.** Runtime lives in monorepo `agents/harness-agent` + `packages/agent-runtime`.

## Prerequisites

```powershell
pip install -e "packages/agent-runtime[harness]"
pip install -e packages/a2a-sdk
pip install -r agents/harness-agent/requirements.txt
```

Per-runner CLIs / keys (see [harness-migration.md](../../../../docs/architecture/harness-migration.md)):

| Profile | Needs |
|---------|--------|
| claude-code | `claude` on PATH |
| deepseek-harness | `DEEPSEEK_API_KEY` |
| pi | `pi` CLI or `PI_API_KEY` / `OPENAI_API_KEY` |
| openclaw | `openclaw` on PATH |
| hermes | `hermes` on PATH |

Optional: set `AOP_REPO_ROOT` if plugins are relocated outside the monorepo.

## Manual smoke (one agent)

```powershell
cd apps\client\aop-node\plugins\claude-code
python -u run.py
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
