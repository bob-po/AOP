# 高可用部署指南

## 概述

AOP平台支持高可用部署，通过多实例部署、负载均衡和故障转移来确保系统稳定性和可用性。

## 架构组件

### 高可用架构图

```
                    ┌─────────────┐
                    │   Nginx LB  │
                    │  (端口 80)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────▼────┐  ┌───▼────┐  ┌───▼────┐
         │Gateway  │  │Gateway │  │Gateway │
         │:8080    │  │:8080   │  │:8080   │
         └────┬────┘  └───┬────┘  └───┬────┘
              │            │            │
              └────────────┼────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────▼────┐  ┌───▼────┐  ┌───▼────┐
         │Orch-1   │  │Orch-2  │  │Orch-3  │
         │:8090    │  │:8091   │  │:8092   │
         └────┬────┘  └───┬────┘  └───┬────┘
              │            │            │
              └────────────┼────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
    │PostgreSQL│     │  Redis  │     │  MinIO  │
    │  (主从)  │     │ (集群)  │     │ (分布式) │
    └─────────┘      └─────────┘      └─────────┘
```

## 部署步骤

### 1. 使用高可用配置文件

```bash
cd deployments
docker compose -f docker-compose.ha.yml up -d
```

### 2. 验证部署状态

```bash
# 检查所有服务状态
docker compose -f docker-compose.ha.yml ps

# 检查Orchestrator实例
curl http://localhost:8090/health
curl http://localhost:8091/health
curl http://localhost:8092/health

# 检查Gateway负载均衡
curl http://localhost:8080/health
```

### 3. 测试故障转移

```bash
# 停止一个Orchestrator实例
docker stop aop-orchestrator-1

# 验证系统仍然可用
curl http://localhost:8080/v1/tasks
```

## 配置说明

### 环境变量

#### Gateway配置
- `ORCHESTRATOR_URLS`: 逗号分隔的Orchestrator实例URL列表
  - 示例: `http://orchestrator-1:8090,http://orchestrator-2:8091,http://orchestrator-3:8092`
- `DATABASE_URL`: PostgreSQL连接字符串
- `REDIS_URL`: Redis连接字符串

#### Orchestrator配置
- `ORCHESTRATOR_ID`: 实例唯一标识符
- `ORCHESTRATOR_PORT`: 实例监听端口
- `DATABASE_URL`: PostgreSQL连接字符串
- `REDIS_URL`: Redis连接字符串

### Nginx负载均衡配置

Nginx配置文件位于 `deployments/nginx/nginx.conf`，包含：

- **负载均衡策略**: least_conn（最少连接）
- **健康检查**: 基于max_fails和fail_timeout
- **连接保持**: keepalive连接池
- **速率限制**: API和通用请求限制
- **WebSocket支持**: 升级头处理

## 数据库高可用

### PostgreSQL主从复制

```yaml
# 在docker-compose.ha.yml中添加PostgreSQL主从配置
postgres-master:
  image: postgres:16-alpine
  environment:
    POSTGRES_REPLICATION_MODE: master
    POSTGRES_REPLICATION_USER: replicator
    POSTGRES_REPLICATION_PASSWORD: replicator_password

postgres-slave:
  image: postgres:16-alpine
  environment:
    POSTGRES_REPLICATION_MODE: slave
    POSTGRES_MASTER_SERVICE: postgres-master
    POSTGRES_REPLICATION_USER: replicator
    POSTGRES_REPLICATION_PASSWORD: replicator_password
```

### Redis集群

```yaml
# Redis Sentinel配置
redis-master:
  image: redis:7-alpine
  command: redis-server --appendonly yes

redis-slave-1:
  image: redis:7-alpine
  command: redis-server --slaveof redis-master 6379 --appendonly yes

redis-sentinel:
  image: redis:7-alpine
  command: redis-sentinel /etc/redis/sentinel.conf
```

## 监控和告警

### Prometheus配置

在高可用部署中，Prometheus会监控所有实例：

```yaml
scrape_configs:
  - job_name: 'orchestrator-ha'
    static_configs:
      - targets: ['orchestrator-1:8090', 'orchestrator-2:8091', 'orchestrator-3:8092']
    metrics_path: '/metrics'
```

### 告警规则

高可用特定的告警规则：

- **OrchestratorDown**: 单个Orchestrator实例不可用
- **GatewayDown**: Gateway服务不可用
- **DatabaseReplicationLag**: 数据库复制延迟过高
- **RedisClusterDown**: Redis集群节点不可用

## 性能优化

### 连接池配置

在Gateway和Orchestrator中配置适当的连接池大小：

```go
// PostgreSQL连接池
pool, err := pgxpool.New(ctx, databaseURL)
pool.Config().MaxConns = 50  // 根据负载调整

// Redis连接池
rdb := redis.NewClient(&redis.Options{
    PoolSize: 20,  // 根据负载调整
})
```

### 缓存策略

- **Redis缓存**: 缓存Agent注册信息、Skill索引
- **本地缓存**: Orchestrator实例级别的缓存
- **缓存失效**: 基于TTL和事件驱动的缓存失效

## 故障恢复

### 自动故障转移

1. **实例级故障**: Nginx自动将流量路由到健康实例
2. **数据库故障**: PostgreSQL主从自动切换
3. **Redis故障**: Sentinel自动故障转移

### 手动故障转移

```bash
# 手动切换PostgreSQL主从
docker exec -it aop-postgres-slave pg_ctl promote

# 手动提升Redis从节点
docker exec -it aop-redis-slave redis-cli SLAVEOF NO ONE
```

## 备份和恢复

### 数据备份

```bash
# PostgreSQL备份
docker exec aop-postgres pg_dump -U aop aop > backup.sql

# Redis备份
docker exec aop-redis redis-cli BGSAVE
docker cp aop-redis:/data/dump.rdb ./redis_backup.rdb
```

### 数据恢复

```bash
# PostgreSQL恢复
docker exec -i aop-postgres psql -U aop aop < backup.sql

# Redis恢复
docker cp ./redis_backup.rdb aop-redis:/data/dump.rdb
docker restart aop-redis
```

## 扩展策略

### 水平扩展

```yaml
# 添加更多Orchestrator实例
orchestrator-4:
  build:
    context: ../apps/orchestrator
    dockerfile: Dockerfile
  environment:
    - ORCHESTRATOR_ID=orchestrator-4
    - ORCHESTRATOR_PORT=8093
  ports:
    - "8093:8093"
```

### 垂直扩展

```yaml
# 增加资源限制
orchestrator-1:
  deploy:
    resources:
      limits:
        cpus: '2.0'
        memory: 4G
      reservations:
        cpus: '1.0'
        memory: 2G
```

## 安全加固

### 网络隔离

```yaml
# 使用Docker网络隔离
networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true  # 仅内部访问
```

### TLS/SSL配置

```nginx
# 在nginx.conf中启用HTTPS
server {
    listen 443 ssl http2;
    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
}
```

## 故障排查

### 常见问题

1. **服务启动失败**
   - 检查端口冲突: `netstat -tulpn`
   - 检查日志: `docker compose logs <service>`

2. **负载均衡不工作**
   - 验证Nginx配置: `docker exec aop-nginx-lb nginx -t`
   - 检查上游服务健康状态

3. **数据库连接问题**
   - 验证连接字符串
   - 检查数据库连接池配置

### 监控命令

```bash
# 实时监控容器状态
docker stats

# 查看服务日志
docker compose -f docker-compose.ha.yml logs -f

# 检查网络连接
docker network inspect deployments_default
```

## 最佳实践

1. **资源规划**: 根据预期负载规划CPU、内存和存储
2. **监控告警**: 配置完善的监控和告警系统
3. **定期备份**: 定期备份数据库和配置
4. **灾难恢复**: 制定和测试灾难恢复计划
5. **安全更新**: 定期更新依赖和安全补丁
6. **容量规划**: 监控资源使用情况，及时扩容

## 相关文档

- [监控系统设置](./monitoring-setup.md)
- [API文档](./api.md)
- [数据库设计](./database.md)
- [Redis设计](./redis.md)