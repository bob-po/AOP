---
name: project-analysis
description: Detect project type, frameworks, ports, and packaging signals for deployment planning.
---

# Project Analysis Skill

When analyzing a repository:

1. Check for `docker-compose.yml` / `compose.yaml` first.
2. Check for `Dockerfile`.
3. Detect Node.js via `package.json` and lockfiles (`pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`).
4. Detect Python via `requirements.txt`, `pyproject.toml`, `Pipfile`, `manage.py`, `app.py`, `main.py`.
5. Extract likely ports from `EXPOSE`, compose ports, `PORT` env, framework defaults.
6. Prefer existing compose/Dockerfile over generated ones.
7. Never invent frameworks that are not evidenced by files or dependencies.
