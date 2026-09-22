---
name: nodejs-deployment
description: Build and run Node.js apps (Express, Next, Vite, Nest) in Docker.
---

# Node.js Deployment Skill

Defaults:

- Base image: `node:20-alpine`
- Install with the lockfile package manager (`npm ci`, `pnpm install`, `yarn install`)
- Prefer `npm start` / production scripts over `dev` when available
- Next.js: `next start -H 0.0.0.0 -p $PORT` after `next build`
- Default port: 3000

Common repairs:

- Missing `start` script — add one or use `node dist/index.js`
- Native addon build failures — switch to debian base image
- Host binding — ensure `0.0.0.0`
- Lockfile mismatch — fall back to non-frozen install
