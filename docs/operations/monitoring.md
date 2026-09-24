# 监控系统设置指南（Phase 21）

## 概述

AOP 集成 Prometheus + Grafana + Alertmanager：

- **Prometheus**：抓取 Gateway / Orchestrator / Worker 指标
- **Grafana**：预置 Overview 面板（`AOP Monitoring` 文件夹）
- **Alertmanager**：规则路由（默认 `null` receiver，本地不外发）

## 快速启动

### 全栈（single compose · observability profile）

```bash
cd deployments
docker compose -f docker-compose.single.yml --profile observability up -d
```

### 仅监控 + 宿主机跑应用

```bash
cd deployments
docker compose -f docker-compose.yml up -d prometheus grafana alertmanager
# 应用在宿主机：8090 / 8080 / worker METRICS_PORT=9092
```

### 访问

| 服务 | URL |
|------|-----|
| Grafana | http://localhost:3001 （admin / admin） |
| Prometheus | http://localhost:9090 |
| Alertmanager | http://localhost:9093 |
| Console | http://localhost:3000 |

Grafana 自动加载 **AOP Platform Overview**（uid `aop-overview`）。

## Scrape 目标

| Job | 路径 | 说明 |
|-----|------|------|
| `orchestrator` | `:8090/metrics` | FastAPI prometheus_client |
| `orchestrator-prom-client` | `:9091/metrics` | 独立 metrics 端口 |
| `orchestrator-legacy` | `:8090/v1/metrics?format=prometheus` | DB 快照指标 |
| `gateway` | `:8080/metrics` | LB 健康目标数等 |
| `worker` | `:9091/metrics`（compose）/ `:9092`（host） | Agent 调用计数主来源 |

配置：`deployments/prometheus/prometheus.yml` · `prometheus.host.yml` · `prometheus.ha.yml`  
告警：`deployments/prometheus/alerts/aop-alerts.yml`

## 关键指标

| 指标 | 来源 |
|------|------|
| `aop_tasks_total` / `aop_agent_calls_total` | 进程内 Counter |
| `aop_agent_latency_seconds` | Histogram |
| `aop_tasks` / `aop_agents` | `/v1/metrics` DB 快照 |
| `aop_task_memories_total` / `aop_tenant_memories_total` | 快照 |
| `aop_gateway_lb_healthy_targets` | Gateway |

## 告警（节选）

- `HighAgentFailureRate` · `HighTaskFailureRate`
- `AgentOffline` · `TaskBacklog` · `HighAgentLatency`
- `GatewayLBNoHealthyTargets`
- `OrchestratorDown` · `GatewayDown` · `WorkerDown`

本地 Alertmanager 默认丢弃通知；生产请改 `deployments/alertmanager/alertmanager.yml` 的 receiver。

## 冒烟

```bash
cd apps/orchestrator
python scripts/phase21_observability.py
```

## 排障

1. Prometheus Targets：http://localhost:9090/targets  
2. Alerts：http://localhost:9090/alerts  
3. Grafana 数据源 uid 必须为 `prometheus`（已在 provisioning 中设置）
