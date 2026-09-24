# 分布式追踪设置指南

## 概述

AOP平台集成了OpenTelemetry分布式追踪，提供跨服务的请求追踪、性能分析和问题诊断能力。

## 架构组件

### 追踪架构图

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│  FastAPI    │    │   Worker    │    │   A2A       │
│  (Orchestrator) │   (Worker)   │    │   Agents    │
└──────┬──────┘    └──────┬──────┘    └──────┬──────┘
       │                  │                  │
       │  OpenTelemetry   │  OpenTelemetry   │  OpenTelemetry
       │  SDK             │  SDK              │  SDK
       └──────────────────┴──────────────────┴──────────────────┘
                             │
                             ▼
                      ┌─────────────┐
                      │   Jaeger    │
                      │  Collector  │
                      └─────────────┘
                             │
                             ▼
                      ┌─────────────┐
                      │   Jaeger    │
                      │    UI       │
                      │  (16686)    │
                      └─────────────┘
```

## 快速启动

### 1. 启动Jaeger

```bash
cd deployments
docker compose up -d jaeger
```

### 2. 配置环境变量

```bash
# Orchestrator环境变量
export JAEGER_ENDPOINT=jaeger:6831
export OTEL_SAMPLE_RATE=1.0
export ENVIRONMENT=production
```

### 3. 访问Jaeger UI

打开浏览器访问 http://localhost:16686

## 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `JAEGER_ENDPOINT` | Jaeger agent地址 | `localhost:6831` |
| `OTLP_ENDPOINT` | OTLP collector地址 | `localhost:4317` |
| `OTEL_SAMPLE_RATE` | 采样率 (0.0-1.0) | `1.0` |
| `OTEL_CONSOLE_EXPORT` | 启用控制台导出 | `false` |
| `ENVIRONMENT` | 部署环境 | `development` |

### Python代码配置

```python
from tracing import TracingConfig, setup_tracing, instrument_fastapi

# 自定义配置
config = TracingConfig(
    service_name="aop-orchestrator",
    service_version="1.0.0",
    environment="production",
    jaeger_endpoint="jaeger:6831",
    sample_rate=0.1  # 10% 采样率
)

# 初始化追踪
setup_tracing(config)

# 在FastAPI应用中启用
instrument_fastapi(app)
```

## 使用追踪

### 1. 自动追踪

以下组件会自动被追踪：

- **FastAPI**: HTTP请求和响应
- **HTTPX**: 外部HTTP调用
- **Redis**: Redis操作
- **PostgreSQL**: 数据库查询（需要额外配置）

### 2. 手动追踪

```python
from tracing import get_tracer, trace_operation, set_span_attribute, record_span_exception

tracer = get_tracer("my_component")

# 使用上下文管理器
with trace_operation("my_operation", operation_id="123") as span:
    # 添加属性
    set_span_attribute("user.id", "user-123")
    set_span_attribute("operation.type", "custom")
    
    try:
        result = perform_operation()
        set_span_attribute("result.status", "success")
    except Exception as e:
        record_span_exception(e)
        raise
```

### 3. 在Worker中使用

```python
# Worker中的追踪示例
def handle(self, fields: dict[str, str]) -> None:
    task_id = fields["task_id"]
    
    with trace_operation(
        "worker.handle",
        task_id=task_id,
        node_key=fields["node_key"],
        skill=fields["skill"]
    ) as span:
        # 执行逻辑
        result = self.process_task(task_id)
        
        # 添加结果信息
        set_span_attribute("worker.result", "success")
```

## 追踪数据查看

### Jaeger UI

1. **搜索追踪**
   - 服务名称: `aop-orchestrator`
   - 操作名称: `POST /v1/tasks`
   - 时间范围: 选择时间范围
   - 标签: `task_id=xxx`

2. **查看追踪详情**
   - 点击追踪ID查看完整调用链
   - 查看每个span的详细信息
   - 分析性能瓶颈

3. **服务依赖图**
   - 在Jaeger UI中查看服务依赖关系
   - 分析服务间调用模式

### 查询API

```bash
# 查询特定任务的追踪
curl "http://localhost:16686/api/traces?service=aop-orchestrator&tag=task_id:xxx"

# 查询特定操作的追踪
curl "http://localhost:16686/api/traces?service=aop-orchestrator&operation=worker.handle"
```

## 性能分析

### 1. 识别慢查询

在Jaeger UI中：
1. 按持续时间排序追踪
2. 查看长时间运行的span
3. 分析具体操作的耗时

### 2. 错误追踪

```python
# 记录异常到追踪
try:
    risky_operation()
except Exception as e:
    record_span_exception(e)
    # 异常会自动显示在Jaeger UI中
```

### 3. 分布式上下文传播

追踪会自动跨服务传播：

```
Gateway → Orchestrator → Worker → A2A Agent
```

每个服务都会继承父span的trace context，形成完整的调用链。

## 采样策略

### 采样率配置

```python
config = TracingConfig(
    sample_rate=0.1  # 10% 采样率，适合高流量场景
)
```

### 采样建议

| 场景 | 采样率 | 说明 |
|------|--------|------|
| 开发环境 | 1.0 | 捕获所有追踪 |
| 测试环境 | 0.5 | 50% 采样 |
| 生产环境低流量 | 0.1 | 10% 采样 |
| 生产环境高流量 | 0.01 | 1% 采样 |

## 高级配置

### 1. 自定义导出器

```python
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

otlp_exporter = OTLPSpanExporter(
    endpoint="localhost:4317",
    insecure=True
)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
```

### 2. 多导出器

```python
# 同时导出到Jaeger和OTLP
jaeger_exporter = JaegerExporter(agent_host_name="jaeger", agent_port=6831)
otlp_exporter = OTLPSpanExporter(endpoint="localhost:4317", insecure=True)

provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
```

### 3. 自定义资源属性

```python
resource = Resource.create({
    SERVICE_NAME: "aop-orchestrator",
    "service.version": "1.0.0",
    "deployment.environment": "production",
    "host.name": "orchestrator-1",
    "k8s.pod.name": os.getenv("POD_NAME"),
    "k8s.namespace": os.getenv("POD_NAMESPACE"),
})
```

## 故障排查

### 1. 追踪数据不显示

```bash
# 检查Jaeger状态
docker logs aop-jaeger

# 检查环境变量
echo $JAEGER_ENDPOINT
echo $OTEL_SAMPLE_RATE

# 检查网络连接
docker exec aop-orchestrator ping jaeger
```

### 2. 缺少某些span

- 确认相关库已正确instrument
- 检查采样率设置
- 验证context propagation

### 3. 性能影响

```python
# 降低采样率减少性能影响
config = TracingConfig(sample_rate=0.01)

# 使用异步导出器
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
provider.add_span_processor(SimpleSpanProcessor(exporter))
```

## 最佳实践

### 1. 命名规范

```python
# 好的span命名
trace_operation("agent.call_search")
trace_operation("database.query_tasks")
trace_operation("cache.get_user")

# 避免过于笼统
trace_operation("operation")  # 不好
trace_operation("do_something")  # 不好
```

### 2. 属性添加

```python
# 添加有意义的属性
set_span_attribute("agent.id", agent_id)
set_span_attribute("agent.skill", skill)
set_span_attribute("task.status", "completed")
set_span_attribute("cache.hit", true)
```

### 3. 错误处理

```python
# 记录详细的错误信息
try:
    operation()
except ValueError as e:
    set_span_attribute("error.type", "validation")
    set_span_attribute("error.message", str(e))
    record_span_exception(e)
except NetworkError as e:
    set_span_attribute("error.type", "network")
    set_span_attribute("error.endpoint", endpoint)
    record_span_exception(e)
```

## 集成其他系统

### 1. Grafana集成

Jaeger数据可以集成到Grafana：

```yaml
# Grafana数据源配置
{
  "type": "jaeger",
  "url": "http://jaeger:16686",
  "access": "proxy"
}
```

### 2. Prometheus集成

追踪指标可以导出到Prometheus：

```python
from opentelemetry.exporter.prometheus import PrometheusMetricReader

reader = PrometheusMetricReader()
meter = MeterProvider(metric_readers=[reader])
```

### 3. 日志关联

将trace ID添加到日志中：

```python
from tracing import trace
import logging

current_span = trace.get_current_span()
trace_id = current_span.get_span_context().trace_id if current_span else "unknown"
logger.info(f"Processing request {trace_id}")
```

## 相关文档

- [监控系统设置](./monitoring.md)
- [错误处理指南](./error-handling-guide.md)
- [高可用部署](./high-availability-setup.md)
- [OpenTelemetry文档](https://opentelemetry.io/docs/)
- [Jaeger文档](https://www.jaegertracing.io/docs/)