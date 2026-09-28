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
| `/tasks/[id]` | DAG + Live Trace + Artifacts |
| `/agents` | Registry + router preview by **agent_key**（`claude-code` / `deepseek-harness` / `pi` / `openclaw` / `hermes`） |
| `/workflows` | 编排模板（节点用 harness agent_key） |
| `/settings` | API Keys · RBAC · 审计 · 用量 · 配额 · 出站 |
| `/login` | 开发账号 `admin@aop.local` / `aop_admin_dev` |

全栈启动见 [docs/guides/getting-started.md](../../docs/guides/getting-started.md)。

## Stack

Next.js 15 · React 19 · Tailwind · Fraunces / Manrope / IBM Plex Mono
