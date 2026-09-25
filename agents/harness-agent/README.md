# Harness Agent — sole A2A agent deployment

Specialty agents (search/rag/report/…) were removed. This directory hosts N virtual
agents = harness × role profile.

| Profile | Port | Skills |
|---------|------|--------|
| `claude-coder` | 8011 | code-execution, code-assist |
| `claude-researcher` | 8012 | web-research, research-summarize, web-search |
| `pi-coder` | 8013 | code-execution, code-assist |
| `pi-researcher` | 8014 | web-research, research-summarize, web-search |
| `deepseek-coder` | 8015 | code-execution, code-assist |
| `deepseek-researcher` | 8016 | web-research, research-summarize, web-search |

## Remote host (Claude Code–style)

With A2A OS reachable at `http://<os>:8000`:

```powershell
irm http://<os>:8000/install/claude-coder.ps1 | iex
```

```bash
curl -fsSL http://<os>:8000/install/claude-coder.sh | bash
```

Installs under `~/.aop/agents/<profile>` with vendored `agent-runtime`, then register back to the OS.

## Local monorepo

```powershell
pip install -e "packages/agent-runtime[harness]"
pip install -r agents/harness-agent/requirements.txt
python scripts/start_and_register_agents.py
```

See [`docs/architecture/harness-migration.md`](../../docs/architecture/harness-migration.md).
