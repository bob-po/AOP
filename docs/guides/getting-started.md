# AOP 项目启动指南（本地开发）

本文档梳理 AOP（A2A Agent Orchestration Platform）本地启动的完整步骤、端口与环境变量约定，以及启动过程中最常踩的坑和排查方法。

> 快速入口：根目录 [README.md](../README.md) 也有「快速开始」，本文档在此基础上补充了**依赖版本要求、端口占用、报错排查**等实战细节。

---

## 1. 项目结构一览

| 模块 | 语言 | 端口 | 说明 |
|------|------|------|------|
| Postgres 16 | 容器 | `5432` | 元数据库（`aop/aop/aop`） |
| Redis 7 | 容器 | `6379` | Streams / 队列 / 锁 / PubSub |
| MinIO | 容器 | `9000`(API) / `9001`(控制台) | 产物存储 |
| Prometheus / Grafana | 容器 | `9090` / `3001` | 可观测（可选） |
| Alertmanager / Webhook | 容器 | `9093` / `5000` | 告警（可选） |
| Jaeger | 容器 | `16686` | 链路追踪（可选） |
| **Orchestrator** | Python (FastAPI) | `8090`（指标 `9091`） | 编排核心 API |
| **Worker** | Python | 无（消费 Redis） | 执行引擎 |
| **Outbox Processor** | Python | 无（轮询 PG） | P36.2 outbox 投递（**必需**） |
| **Gateway** | Go | `8080` | 注册中心 + 反向代理 + 鉴权 |
| **Web Console** | Next.js 15 | `3000` | 前端 |
| **Harness virtual agents** | Python | `8011`–`8016` | Claude/Pi/DeepSeek × coder|researcher（`agents/harness-agent`） |

启动顺序（依赖关系）：**基础设施 → 数据库迁移 → Orchestrator → Worker → Outbox Processor → Gateway → Agents → Web**。

> ⚠️ **Outbox Processor 是 Phase 36.2 新增的必需服务**。缺少它时，任务的首批就绪节点会一直卡在 PostgreSQL `outbox_events` 表（状态 `pending`），任务表现为 `running` 但节点永远停在 `ready`。

---

## 2. 前置依赖

| 依赖 | 版本要求 | 说明 |
|------|----------|------|
| Docker + Compose v2 | 任意较新 | 起 Postgres/Redis/MinIO；用 `docker compose`（带空格），不是旧版 `docker-compose` |
| Python | **≥ 3.11**（Docker 用 3.12） | `a2a-sdk` 要求 `>=3.11`，代码用到 `X | None` 等新语法 |
| Node.js | **≥ 18.18**（建议 20） | Next.js 15 要求 |
| Go | **≥ 1.22** | `apps/gateway/go.mod` 声明 `go 1.22` |
| pip / npm / go | — | 国内建议配置镜像（见 §7.1） |

---

## 3. 完整启动步骤

> Windows 用户注意：README 里用 `set XXX=yyy` 是 **CMD** 语法；在 **PowerShell** 用 `$env:XXX="yyy"`，在 **Git Bash** 用 `export XXX=yyy`。

### 3.1 起基础设施

```bash
docker compose -f deployments/docker-compose.yml up -d postgres redis minio
```

确认三个容器健康：

```bash
docker compose -f deployments/docker-compose.yml ps
# 或用 docker ps 查看 aop-postgres / aop-redis / aop-minio 是否为 healthy
```

> `minio-init` 容器会自动创建 `aop-artifacts` 桶并设为匿名可下载；若它退出后桶没建好，见 §7.9。

### 3.2 跑数据库迁移

```bash
pip install "psycopg[binary]>=3.2"     # migrate.py 依赖，先装
python infrastructure/postgres/migrate.py
# 查看状态
python infrastructure/postgres/migrate.py --status
```

输出 `applied N migration(s)` 即成功。默认连接 `postgresql://aop:aop@127.0.0.1:5432/aop`。

### 3.3 启动 Orchestrator

```bash
cd apps/orchestrator
pip install -r requirements.txt
pip install -e ../../packages/a2a-sdk        # 从仓库根目录：pip install -e packages/a2a-sdk
uvicorn main:app --host 0.0.0.0 --port 8090
```

验证：`curl http://127.0.0.1:8090/health` → `{"status":"ok",...}`。

> 也可直接 `python main.py`（内部 `__main__` 会读 `ORCHESTRATOR_PORT` 并额外起指标服务）。

### 3.4 启动 Worker（另开终端）

```bash
cd apps/orchestrator
python worker.py
```

Worker 消费 Redis Streams 执行 DAG，**必须与 Orchestrator 同时跑**，否则任务会一直 pending。

### 3.4b 启动 Outbox Processor（另开终端，Phase 36.2 必需）

```bash
cd apps/orchestrator
python outbox_processor_service.py
```

P36.2 引入 outbox 模式：任务创建时的首批就绪节点先写入 PostgreSQL `outbox_events` 表，由本服务轮询投递到 Redis Stream `a2a.execution.queue`。**不启动它，任务会卡死在 `outbox_events(pending)`、节点停在 `ready` 不执行**。

> 后续节点（下游节点）由 Worker 执行完成后经 `executor` 直接 `XADD` 入流，不经过 outbox；但**首批节点必须依赖本服务**。

### 3.5 启动 Gateway

```bash
cd apps/gateway
go mod tidy
go run ./cmd
# Windows CMD:
#   set ORCHESTRATOR_URL=http://127.0.0.1:8090
# 或 Git Bash:
#   export ORCHESTRATOR_URL=http://127.0.0.1:8090
```

Gateway 启动时会：连接 PG/Redis、`SEED_DEV_KEY` 时种入开发 Key、`EnsureDevUser` 种入管理员账号。

### 3.6 启动 Agents 并注册

```bash
pip install -e packages/a2a-sdk      # 确保已装
python scripts/start_and_register_agents.py
```

脚本会按 profile 在 `8011`–`8016` 拉起 harness 虚拟 Agent（claude/pi/deepseek × coder|researcher），健康检查通过后向 Gateway 注册。远端主机可用 Marketplace 一键安装（`irm …/install.ps1 | iex`），见 [harness-migration.md](../architecture/harness-migration.md)。

```powershell
# 仅启动部分 profile（可选）
$env:HARNESS_PROFILES="claude-coder,deepseek-coder"
python scripts/start_and_register_agents.py
```

### 3.7 启动 Web Console

```bash
cd apps/web
npm install
npm run dev
```

3000端口占用时运行下列命令

```bash
Get-Process -Id (Get-NetTCPConnection -LocalPort 3000).OwningProcess -ErrorAction SilentlyContinue | Stop-Process -Force
```

打开 <http://127.0.0.1:3000>，用 `/login` 登录：

| 项 | 值 |
|----|----|
| 开发账号 | `admin@aop.local` / `aop_admin_dev` |
| 覆盖密码 | 环境变量 `SEED_ADMIN_PASSWORD` |
| 开发 API Key | `aop_sk_dev_local_0000000000000001` |

---

## 4. 端口占用表（冲突排查用）

| 端口 | 服务 | 端口 | 服务 |
|------|------|------|------|
| `5432` | Postgres | `8090` | Orchestrator |
| `6379` | Redis | `9091` | 指标服务（orchestrator & worker 默认都抢） |
| `9000/9001` | MinIO | `8080` | Gateway |
| `9090` | Prometheus | `3000` | Web |
| `3001` | Grafana | `8011–8016` | Harness virtual agents |
| `9093` | Alertmanager | `5000` | Webhook |

---

## 5. 环境变量速查

### Orchestrator（Python）

| 变量 | 默认值 |
|------|--------|
| `DATABASE_URL` | `postgresql://aop:aop@127.0.0.1:5432/aop` |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `MINIO_ENDPOINT` | `127.0.0.1:9000` |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `aopminio` / `aopminio123` |
| `MINIO_BUCKET` | `aop-artifacts` |
| `ORCHESTRATOR_PORT` | `8090` |
| `METRICS_PORT` | `9091` |
| `GATEWAY_URL` | `http://127.0.0.1:8080` |
| `OUTBOX_POLL_INTERVAL` | `1.0`（outbox 处理器轮询间隔，秒） |
| `OUTBOX_BATCH_SIZE` | `100`（outbox 处理器每批处理数） |
| `STRIPE_SECRET_KEY` | 空（本地计费可 dry-run） |

### Gateway（Go，`internal/config/config.go`）

| 变量 | 默认值 |
|------|--------|
| `GATEWAY_ADDR` | `:8080` |
| `DATABASE_URL` | `postgres://aop:aop@127.0.0.1:5432/aop?sslmode=disable` |
| `REDIS_ADDR` / `REDIS_PASSWORD` | `127.0.0.1:6379` / 空 |
| `ORCHESTRATOR_URL` | `http://127.0.0.1:8090` |
| `ORCHESTRATOR_URLS` | 逗号分隔多实例（负载均衡） |
| `AUTH_REQUIRED` | 本地 `false`，部署 `true` |
| `SEED_DEV_KEY` | 默认 = `!AUTH_REQUIRED` |
| `DEFAULT_TENANT_ID` | `00000000-0000-0000-0000-000000000001` |

### Web（Next.js，`apps/web/.env.local`）

| 变量 | 默认值 |
|------|--------|
| `NEXT_PUBLIC_API_BASE` | `http://127.0.0.1:8080` |
| `NEXT_PUBLIC_API_KEY` | `aop_sk_dev_local_0000000000000001`（`AUTH_REQUIRED=true` 时用） |

---

## 6. 启动成功后如何自检

```bash
curl http://127.0.0.1:8090/health          # orchestrator ok
curl http://127.0.0.1:8080/v1/agents       # gateway 返回注册的 agents
curl http://127.0.0.1:3000                  # web console

# outbox 处理器是否在跑（应该看到 "Starting outbox processor service"）
# 建任务后确认 outbox_events 里 pending 被及时清空：
docker exec aop-postgres psql -U aop -d aop -c "SELECT status, count(*) FROM outbox_events GROUP BY status;"
```

浏览器：`/tasks` 建一个任务，观察 DAG 是否推进（首批节点经 outbox → Redis → Worker → Agent 执行）。

---

## 7. 常见问题与排查

### 7.1 依赖下载慢 / 超时（国内网络）

```bash
# Go
export GOPROXY=https://goproxy.cn,direct
# npm
npm config set registry https://registry.npmmirror.com
# pip
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
```

### 7.2 `docker compose` 报 command not found

旧版 Docker 用 `docker-compose`（连字符）。新版 Compose v2 用 `docker compose`（空格）。可执行 `docker compose version` 确认。

### 7.3 Docker 容器起不来 / 一直 unhealthy

```bash
docker compose -f deployments/docker-compose.yml logs postgres
```

- Postgres：确认 `5432` 未被本机自装 PG 占用，或改 `docker-compose.yml` 端口映射。
- 首次启动会执行 `infrastructure/postgres/init/*.sql`，其中 `001_init.sql` 有 `CREATE EXTENSION pgcrypto`，需 Postgres 支持（官方镜像自带）。

### 7.4 端口被占用（5432 / 6379 / 8080 / 3000 / 8011…）

```bash
# Windows（PowerShell）查占用
netstat -ano | findstr :8080
taskkill /PID <PID> /F
```

本地常见：已装了 Postgres/Redis 服务 → 与容器端口冲突，停掉其一或改映射。Harness Agent 端口冲突则 `start_and_register_agents.py` 会自动跳过已健康实例。

### 7.5 Python 版本过低（< 3.11）

`pip install -e packages/a2a-sdk` 或 `pip install -r requirements.txt` 报 `requires-python`、语法错误（`X | None`）。→ 用 Python 3.11/3.12。

### 7.6 `migrate.py` 报 `ModuleNotFoundError: No module named 'psycopg'`

注意是 **psycopg（v3）**，不是 `psycopg2`。Windows 无编译工具链时务必装 `psycopg[binary]`：

```bash
pip install "psycopg[binary]>=3.2"
```

### 7.7 Gateway 启动即退出：`postgres connect / ping` 或 `redis ping` 失败

- 确认 3.1 的容器已起且 healthy；
- 确认数据库 URL 正确（Gateway 用 `postgres://`、Orchestrator 用 `postgresql://`，二者都行，但注意 `sslmode=disable`）；
- 若自定义了 PG 密码，需同步改 `DATABASE_URL`。

### 7.8 Gateway 日志 `proxy error: dial tcp ...:8090: connect refused`

Orchestrator 没在 `8090` 监听。先起 Orchestrator，再请求 Gateway 代理。Windows 下高频轮询会引发临时端口/`TIME_WAIT` 压力，可重启 Gateway 并降低前端刷新频率。

### 7.9 MinIO 桶不存在 → 上传产物报 `NoSuchBucket`

`minio-init` 容器负责 `mc mb local/aop-artifacts`。若失败：

```bash
docker compose -f deployments/docker-compose.yml run --rm minio-init
# 或进入 minio 容器手动 mc mb local/aop-artifacts
```

### 7.10 Agent 启动 / 注册失败

- Gateway 未启动 → 脚本注册阶段报 `Connection error`；
- Agent 的 `fastapi`/`uvicorn`/`httpx` 未装 → 脚本会打印 FAIL 及日志尾部（`.uvicorn-<port>.log`）；
- `AUTH_REQUIRED=true` 时需要 `GATEWAY_API_KEY`/`AOP_API_KEY` 环境变量，脚本才会带 `Authorization` 头。

### 7.11 任务创建后一直 `pending` / 不执行

Worker 没跑。确认 `python worker.py` 在运行，且能连上 Redis（`redis://127.0.0.1:6379/0`）。

### 7.11b 任务 `running` 但节点永远停在 `ready` / 不分配 agent

P36.2 起这是 **outbox 处理器没跑** 的典型症状。任务首批就绪节点写进了 PostgreSQL `outbox_events` 表（`status='pending'`），等待 `outbox_processor_service.py` 投递到 Redis。排查：

```bash
# 1. 确认 outbox 处理器在跑
cd apps/orchestrator && python outbox_processor_service.py

# 2. 查看卡住的 pending 事件
docker exec aop-postgres psql -U aop -d aop -c \
  "SELECT event_type, payload->>'node_key', status FROM outbox_events WHERE status='pending';"

# 3. 看 Redis 执行流是否增长（有就绪节点入流应持续增加）
docker exec aop-redis redis-cli XLEN a2a.execution.queue
```

> 历史遗留的 P36.2 outbox 处理器存在**自死锁 bug**（`SELECT ... FOR UPDATE SKIP LOCKED` 持锁，随后 `publish_to_redis` 用第二个连接 UPDATE 同一批行导致死锁，见 `pg_stat_activity` 里 `idle in transaction` + `wait_event=transactionid`）。该 bug 已修复：Redis 投递与「标记 processed」改为共用同一连接。若你拉到的是未修复版本，任务会永久卡在 `outbox_events`。

### 7.12 `429` + `quota_concurrent`

租户并发配额已满，或存在卡在 `running` 的旧任务。到 Settings「配额」调高，或取消/清理旧任务。

### 7.13 指标端口 `9091` 冲突

`orchestrator` 和 `worker` 都默认起 `METRICS_PORT=9091` 的指标服务。二者同时跑时后启动者抢不到端口（代码有 try/except，不影响主服务）。如需都给指标，可用 `METRICS_PORT` 给其中一个设不同端口。

### 7.14 Stripe / 计费相关报错

本地未配 `STRIPE_SECRET_KEY` 时，`/v1/billing/*` 相关接口会返回 500 或 dry-run 提示，属预期。完整走 Stripe Checkout 需配 `STRIPE_SECRET_KEY` + `STRIPE_WEBHOOK_SECRET`（见 [billing-invoice.md](./billing-invoice.md)）。

### 7.15 改了 `NEXT_PUBLIC_*` 不生效

`NEXT_PUBLIC_*` 在 **构建期**注入。dev 模式改 `.env.local` 后重启 `npm run dev`；部署镜像需 `./deploy.sh rebuild`。

### 7.16 登录失败 / 没有管理员账号

Gateway 启动时 `EnsureDevUser` 会自动种入 `admin@aop.local`；也可手动：

```bash
cd apps/orchestrator && python scripts/phase25_auth_users.py
```

前提是已跑过 `migrate.py`（`006_user_auth.sql` 已应用）。

---

## 8. 一键部署（Docker Compose，单机云）

本地开发之外，可在 Linux 云服务器用 Compose 一键拉起全部服务：

```bash
cd deployments
cp .env.example .env
# 编辑 AOP_PUBLIC_HOST=<公网IP或域名>
chmod +x deploy.sh
./deploy.sh up
```

详见 [deployments/README.md](../deployments/README.md)。部署默认 `AUTH_REQUIRED=true`，访问 <http://<主机>:3000>。

> 单机 Compose（`docker-compose.single.yml`）已包含 `outbox` 服务（`python outbox_processor_service.py`），与 `worker` 并列启动。早期版本缺失该服务会导致容器化部署同样卡在 `outbox_events(pending)`。

---

## 9. 参考文档索引

- [根 README](../../README.md) — 总览与快速开始
- [文档中心](../README.md) — 分类索引
- [overview.md](../architecture/overview.md) — 架构
- [database.md](../reference/database.md) — 表结构与迁移
- [redis.md](../reference/redis.md) — 队列/锁
- [a2a-protocol.md](../architecture/a2a-protocol.md) / [agent-dev-guide.md](../architecture/agent-dev-guide.md) — 协议与 Agent 规范
- [deployments/README.md](../../deployments/README.md) — 云部署
