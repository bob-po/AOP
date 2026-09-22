---
name: docker-deployment
description: Deploy applications with Docker and Docker Compose under resource limits.
---

# Docker Deployment Skill

Rules:

- Always run untrusted build/run inside Docker with `--memory`, `--cpus`, and `--pids-limit`.
- Prefer `docker compose up -d --build` when compose exists.
- Otherwise generate a minimal production Dockerfile and `docker build` + `docker run -d -p HOST:CONTAINER`.
- Persist real build/run logs; do not summarize as success unless exit code is 0 and container is running.
- Map a single host port for MVP health checks.
- Clean container names with a task-scoped prefix (`deploypilot-<taskId>`).
