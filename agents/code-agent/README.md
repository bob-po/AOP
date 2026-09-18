# Code Agent (Phase 27)

Sandboxed `code-execution` skill: restricted AST evaluation only.

## Security

- Non-root UID 10001
- Compose: `cap_drop: ALL`, `no-new-privileges`, `seccomp=code-agent.json`, `read_only` + tmpfs
- No `import`, file I/O, or subprocess in the evaluator

## Local

```bash
cd agents/code-agent
pip install -r requirements.txt
uvicorn agent:app --port 8007
```

Register: `POST /v1/agents/register` with `http://127.0.0.1:8007`
