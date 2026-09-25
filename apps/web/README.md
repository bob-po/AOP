# AOP Web Console

Next.js console for **A2A OS** — central composer, task DAG, live trace, agents registry.

## Run

```bash
cd apps/web
npm install
# optional China mirror: npm config set registry https://registry.npmmirror.com
npm run dev
```

Open http://127.0.0.1:3000

`NEXT_PUBLIC_API_BASE` defaults to `http://127.0.0.1:8080` (Gateway). CORS is enabled on Gateway.

## Pages

| Route | Purpose |
|-------|---------|
| `/` | Central dialog — create Task |
| `/tasks/[id]` | DAG + Live Trace (1s poll) + Artifacts |
| `/marketplace` | Virtual agents (harness × role) — Register / Deploy (`irm … \| iex`) / zip download |
| `/workflows` | Workflow templates — Run skips Planner |
| `/agents` | Registry + market tab + router preview |

## Stack

Next.js 15 · React 19 · Tailwind · Fraunces / Manrope / IBM Plex Mono
