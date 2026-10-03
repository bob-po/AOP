# AOP Web Console

Next.js console for **A2A OS** — Visual Runtime (Live Agent Network + Command Center), task DAG, live trace, agents registry.

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
| `/` | Command Center — Live Agent Network + Run |
| `/inbox` | HITL 待审批队列（Approve / Reject） |
| `/tasks` | 任务列表 · DAG · 产物 |
| `/agents` | Registry + router preview by **agent_key** |
| `/workflows` | 编排模板（主导航 Flows） |
| `/settings` | API Keys · 团队 · 监控（Chaos 恢复） · 审计 · 配额 |
| `/login` | 开发账号 `admin@aop.local` / `aop_admin_dev` |

全栈一键启动：仓库根目录 `python scripts/dev_up.py`（默认 aop-node 拉起 Harness）。分步见 [getting-started](../../docs/guides/getting-started.md)。

CI：`npm run typecheck` 与 `npm run smoke`（黄金路径文件 + 导航冻结）。

## Stack

Next.js 15 · React 19 · Tailwind · Fraunces / Manrope / IBM Plex Mono
