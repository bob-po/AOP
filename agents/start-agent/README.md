# DeployPilot

AI-powered CLI that turns a GitHub URL or local project path into a running deployment.

**Stack:** TypeScript + Commander · Pi SDK (`@earendil-works/pi-coding-agent`) · Docker sandbox · Pi Skills

```
GitHub / local path
        ↓
  analyze → plan → build → start → health
        ↓              ↑
        └─ repair ×3 ──┘
        ↓
  real URL + logs + task state
```

## Install (DeployPilot CLI)

```bash
cd agents/start-agent
npm install
npm run build
npm link   # optional: expose `deploypilot` globally
```

## A2A Server+Client façade (Phase 2)

DeployPilot remains the TypeScript engine. A Python FastAPI process exposes the
standard A2A surface so start-agent is a first-class peer (10/10 Client-ization):

```bash
pip install -r requirements.txt
python agent.py   # default http://127.0.0.1:8010/
```

JSON-RPC: `message/send`, `tasks/get`, `tasks/cancel`, `tasks/subscribe`, plus
optional autonomous peer delegation via `AgentCollaborator` when `A2A_OS_URL` is set.
Set `START_AGENT_INVOKE_CLI=1` to shell out to `deploypilot` for real deploys.

Requirements:

- Node.js 20+
- Docker Desktop / Engine (for `--mode docker`)
- A Pi-compatible model API key (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`, etc.)

Without model auth, DeployPilot still runs using a **heuristic planner** (no LLM). With auth, Pi Agent plans and repairs from real tool output.

## Quick start

```bash
# Configure defaults
deploypilot config

# Deploy a GitHub repo
deploypilot deploy https://github.com/user/repo

# Deploy local source
deploypilot deploy ./my-project --mode docker

# Inspect / resume / clean
deploypilot status
deploypilot status <task-id>
deploypilot logs <task-id>
deploypilot resume <task-id>
deploypilot clean <task-id>
```

## What MVP guarantees

| Capability | Behavior |
| --- | --- |
| GitHub URL + local path | Clone or copy into `~/.deploypilot/tasks/<id>/workspace` |
| Project detection | Node.js, Python, Docker Compose |
| Plan + build | Heuristic or Pi Agent plan → Docker build/compose |
| Real logs | Written under task `logs/` from docker/compose |
| Auto-repair | Up to 3 attempts driven by agent + re-build/start |
| Health check | Real HTTP probe; URL never invented |
| Resume | Task JSON state machine + logs retained |
| Sandbox limits | `--memory`, `--cpus`, `--pids-limit` on containers |

## Layout

```
src/
  cli.ts                 # entry
  commands/              # deploy/status/logs/resume/clean/config
  agent/                 # Pi runtime, prompts, events
  tools/                 # git, inspector, docker, health, fs, process
  core/                  # orchestrator, state machine, task store, repair loop
  sandbox/               # docker runner + workspace helpers
skills/                  # Pi SKILL.md knowledge packs
templates/docker-compose # Dockerfile / compose templates
```

## Configuration

User config: `~/.deploypilot/config.json`

Environment (also `~/.deploypilot/.env` or project `.env`):

```bash
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
DEPLOYPILOT_MODEL=anthropic/claude-sonnet-4-5
DEPLOYPILOT_MEMORY_LIMIT=512m
DEPLOYPILOT_CPU_LIMIT=1.0
DEPLOYPILOT_MAX_REPAIR=3
```

## Dev

```bash
npm run dev -- deploy ./examples/demo-node
npm run typecheck
```

## Out of scope (post-MVP)

- SSH remote Linux targets (`--target ssh://...` reserved)
- Kubernetes / multi-host fleets
- Redis / Postgres control plane

## License

MIT
