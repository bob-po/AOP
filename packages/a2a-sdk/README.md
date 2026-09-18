# aop-a2a-sdk

Minimal A2A-compatible client used by the AOP Orchestrator.

## Features (Phase 1)

- Fetch Agent Card from `/.well-known/agent-card.json` (fallback: `agent.json`)
- JSON-RPC `message/send` / `tasks/get`
- Internal DTOs: `AgentCard`, `Task`, `Message`, `Artifact`

## Install

```bash
pip install -e packages/a2a-sdk
```

## Usage

```python
from a2a_sdk import A2AClient

client = A2AClient("http://127.0.0.1:8001")
print(client.card.name, client.card.skill_ids())
task = client.send_text("AI orchestration", skill_id="web-search")
print(task.status, task.artifacts)
```
