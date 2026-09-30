# aop-a2a-sdk

A2A client used by the AOP Orchestrator, aligned with
[a2aproject/A2A](https://github.com/a2aproject/A2A) (`protocolVersion` **0.3.0**,
spec pin in `a2a_sdk.protocol.SPEC_COMMIT`).

## Features

- Fetch Agent Card from `/.well-known/agent-card.json` (fallback: `agent.json`)
- JSON-RPC `message/send`, `tasks/get`, `tasks/cancel`
- `message/stream` (SSE) when the card advertises `capabilities.streaming`
- Part wire discriminator **`kind`** (reads `kind` or legacy `type`; writes `kind` only)
- Platform governance/lineage under `metadata` only (inbound still accepts legacy top-level fields)
- Push: `metadata.pushNotificationConfig.url` (+ legacy inbound `callbackUrl`)
- Removed: `tasks/subscribe`, `tasks/delegate` (use `message/stream` / OS discover+route)
OS control plane (`/v1/*` register, DAG, HITL) is **not** part of this package.

## Install

```bash
pip install -e packages/a2a-sdk
```

## Usage

```python
from a2a_sdk import A2AClient

client = A2AClient("http://127.0.0.1:8011")
print(client.card.name, client.card.skill_ids())
task = client.send_text("AI orchestration", skill_id="code-assist")
print(task.status, task.artifacts)
```

## Compliance fixtures

See `tests/fixtures/` and `tests/test_compliance.py`.
