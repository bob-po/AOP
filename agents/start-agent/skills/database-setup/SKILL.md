---
name: database-setup
description: Handle optional database services during compose-based deployments.
---

# Database Setup Skill

MVP guidance:

- If compose already defines Postgres/MySQL/Redis, keep it and wait for healthy dependencies.
- Inject sane defaults for local demos only when missing: `POSTGRES_PASSWORD=deploypilot`, ephemeral volumes.
- Do not expose database ports publicly unless already declared.
- Prefer application health endpoint over DB TCP probes for final acceptance.
- Never wipe unnamed external volumes unless cleaning a DeployPilot-managed project.
