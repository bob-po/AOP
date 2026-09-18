# 单机云部署（Docker Compose）

在一台 Linux 云服务器上用 Docker 拉起完整 AOP：Postgres / Redis / MinIO / 6 Agents / Gateway / Orchestrator / Worker / Web Console。

## 前置

- 2 核 4G+ 推荐（构建 Next/Go 时更稳）
- Docker + Compose v2
- 开放端口：`3000`（Console）、`8080`（Gateway）、`9000/9001`（MinIO，可选）

```bash
# Ubuntu 示例
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
# 重新登录后生效
```

## 一键部署

```bash
git clone <your-aop-repo> AOP
cd AOP/deployments
cp .env.example .env
# 必改：改成云服务器公网 IP 或域名
# AOP_PUBLIC_HOST=1.2.3.4
# 公网建议：
# AUTH_REQUIRED=true   # Phase 15 default
# SEED_DEV_KEY=true

chmod +x deploy.sh
./deploy.sh up
```

`deploy.sh` 会在健康检查后执行 `infrastructure/postgres/migrate.py`（Phase 18），把 `schema_migrations` 与 init SQL 对齐。

完成后访问：

| 服务 | URL |
|------|-----|
| Console | `http://<AOP_PUBLIC_HOST>:3000` |
| Gateway | `http://<AOP_PUBLIC_HOST>:8080` |
| MinIO Console | `http://<AOP_PUBLIC_HOST>:9001` |

API Key：见 `.env` 中 `NEXT_PUBLIC_API_KEY` / `GATEWAY_API_KEY`（Gateway 日志只打印 prefix）

## 可观测性（可选 profile）

```bash
docker compose -f docker-compose.single.yml --profile observability up -d prometheus grafana
# Grafana http://<host>:3001  admin/admin
# Prometheus http://<host>:9090  （抓取 orchestrator:8090 / gateway:8080）
```

宿主机构建（仅 infra）使用 `docker-compose.yml`，Prometheus 挂载 `prometheus.host.yml` 经 `host.docker.internal` 抓取。

## 常用命令

```bash
./deploy.sh status
./deploy.sh logs            # 全部
./deploy.sh logs worker     # 指定服务
./deploy.sh restart
./deploy.sh rebuild         # 代码更新后重建
./deploy.sh down            # 停机保留数据
./deploy.sh destroy         # 停机并删卷（清空 PG/Redis/MinIO）
```

## 配置说明（`.env`）

| 变量 | 含义 |
|------|------|
| `AOP_PUBLIC_HOST` | 浏览器能访问到的主机名/公网 IP |
| `AOP_PUBLIC_SCHEME` | `http` 或 `https`（反代后改 https） |
| `AUTH_REQUIRED` | 部署默认 `true`：强制 Bearer / X-API-Key |
| `SEED_DEV_KEY` | 是否种子本地开发 key（auth 开启时建议轮换后改 `false`） |
| `GATEWAY_API_KEY` | register-agents 注册用 |
| `NEXT_PUBLIC_API_KEY` | 写入 Web 镜像的默认 Key |

> `NEXT_PUBLIC_*` 在 **build** 时注入。改了公网地址后请执行 `./deploy.sh rebuild`。

## 架构（单机）

```
浏览器 → :3000 web
       → :8080 gateway → orchestrator :8090
                      → postgres / redis
worker ← redis streams → agents (search…video)
artifacts → minio :9000
```

Agent 在容器网内用服务名注册（如 `http://search-agent:8001`），Worker 与 Gateway 均可直连。

## 安全建议（上公网）

1. `AUTH_REQUIRED=true`
2. 改掉 MinIO / Postgres 默认密码（需同步改 compose 环境变量）
3. 用 Nginx/Caddy 反代 3000/8080，并上 HTTPS
4. 安全组仅放行必要端口；9001 尽量不暴露公网
5. 轮换并吊销默认 `aop_sk_dev_local_*` 密钥

