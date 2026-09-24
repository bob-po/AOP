# 错误处理和重试机制指南

## 概述

AOP平台实现了增强的错误处理和重试机制，通过智能错误分类、可配置重试策略和熔断器模式来提高系统稳定性和可靠性。

## 核心组件

### 1. 错误分类

系统将错误分为不同类别，每个类别有特定的处理策略：

| 错误类别 | 说明 | 重试策略 |
|---------|------|---------|
| `TRANSIENT` | 临时性错误（网络抖动、临时故障） | 立即重试，指数退避 |
| `PERMANENT` | 永久性错误（配置错误、权限问题） | 不重试 |
| `RATE_LIMIT` | 速率限制 | 激进退避，等待Retry-After |
| `TIMEOUT` | 超时错误 | 增加超时时间后重试 |
| `VALIDATION` | 验证错误 | 不重试 |
| `NETWORK` | 网络错误 | 重试，可能更换路由 |
| `AGENT_UNAVAILABLE` | Agent不可用 | 尝试其他Agent |

### 2. 自定义错误类型

```python
from error_handling import (
    AOPError, AgentError, NetworkError, 
    TimeoutError, ValidationError, RateLimitError
)

# 使用自定义错误
raise AgentError(
    "Agent not responding",
    category=ErrorCategory.AGENT_UNAVAILABLE,
    retryable=True,
    context={"agent_id": "agent-123"}
)

# 带上下文的错误
raise TimeoutError(
    "Database query timeout",
    timeout=30.0,
    context={"query": "SELECT * FROM tasks"}
)
```

### 3. 重试策略

```python
from error_handling import RetryPolicy, with_retry

# 自定义重试策略
retry_policy = RetryPolicy(
    max_attempts=5,           # 最大重试次数
    base_delay=1.0,           # 基础延迟（秒）
    max_delay=60.0,           # 最大延迟（秒）
    exponential_base=2.0,     # 指数退避基数
    jitter=True,              # 添加随机抖动
    retryable_categories={    # 可重试的错误类别
        ErrorCategory.TRANSIENT,
        ErrorCategory.NETWORK,
        ErrorCategory.TIMEOUT
    }
)

# 使用装饰器
@with_retry(policy=retry_policy)
def risky_operation():
    # 可能失败的操作
    pass

# 带重试回调
def on_retry(error, attempt):
    print(f"Attempt {attempt} failed: {error}")

@with_retry(policy=retry_policy, on_retry=on_retry)
def operation_with_callback():
    pass
```

### 4. 熔断器模式

```python
from error_handling import CircuitBreaker, get_circuit_breaker

# 获取或创建熔断器
circuit_breaker = get_circuit_breaker("database_service")

# 使用熔断器保护操作
try:
    result = circuit_breaker.call(database_operation)
except CircuitBreakerOpenError as e:
    # 熔断器打开，降级处理
    return fallback_operation()

# 检查熔断器状态
state = circuit_breaker.get_state()
print(f"Circuit breaker state: {state}")
```

## 在Worker中的应用

### 增强的A2A执行

Worker现在使用增强的错误处理机制：

```python
def _execute_with_retry(self, endpoint: str, query: str, skill: str):
    """执行A2A调用，带有增强的重试逻辑"""
    def execute_a2a():
        result = self.executor.execute(endpoint, query, skill_id=skill)
        if not result.ok:
            # 转换为AOP错误以便更好处理
            raise handle_a2a_error(RuntimeError(f"A2A execution failed"))
        return result
    
    # 使用重试装饰器
    @with_retry(policy=WORKER_RETRY_POLICY)
    def retry_execute():
        return execute_a2a()
    
    return retry_execute()
```

### 智能错误分类

系统自动分类A2A协议错误：

```python
def handle_a2a_error(error: Exception) -> AOPError:
    """将A2A协议错误转换为AOP错误"""
    error_str = str(error).lower()
    
    if "timeout" in error_str:
        return TimeoutError(f"A2A call timeout: {error}", timeout=60.0)
    
    if "connection" in error_str or "network" in error_str:
        return NetworkError(f"A2A network error: {error}")
    
    if "not found" in error_str or "404" in error_str:
        return AgentError(
            f"Agent not found: {error}",
            category=ErrorCategory.AGENT_UNAVAILABLE,
            retryable=False
        )
    
    # 默认分类
    category = classify_error(error)
    return AOPError(f"A2A error: {error}", category=category)
```

## 配置和监控

### 环境变量配置

```bash
# 重试策略配置
RETRY_MAX_ATTEMPTS=3
RETRY_BASE_DELAY=1.0
RETRY_MAX_DELAY=60.0
RETRY_EXPONENTIAL_BASE=2.0
RETRY_JITTER=true

# 熔断器配置
CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
CIRCUIT_BREAKER_RECOVERY_TIMEOUT=60.0
CIRCUIT_BREAKER_SUCCESS_THRESHOLD=2
```

### 监控指标

通过Prometheus监控错误处理效果：

```python
from observability import agent_errors, task_counter

# 记录错误类型
agent_errors.labels(
    agent="search-agent",
    error_type="timeout"
).inc()

# 记录重试次数
task_counter.labels(status="retry").inc()
```

## 最佳实践

### 1. 错误处理层次

```python
# 第一层：业务逻辑错误处理
try:
    result = business_operation()
except ValidationError as e:
    # 验证错误，不重试
    return error_response(e)

# 第二层：网络/临时错误处理
try:
    result = network_operation()
except (NetworkError, TimeoutError) as e:
    # 网络错误，重试
    return retry_operation(e)

# 第三层：系统级错误处理
except Exception as e:
    # 未预期错误，记录并降级
    logger.error(f"Unexpected error: {e}")
    return fallback_response()
```

### 2. 降级策略

```python
def get_agent_response(agent_id, query):
    try:
        # 主要路径：调用Agent
        return call_agent(agent_id, query)
    except AgentError as e:
        if e.category == ErrorCategory.AGENT_UNAVAILABLE:
            # 降级：使用缓存或默认响应
            return get_cached_response(agent_id, query)
        raise
```

### 3. 超时设置

```python
# 分层超时设置
OPERATION_TIMEOUTS = {
    "database": 5.0,      # 数据库操作5秒
    "agent_call": 60.0,    # Agent调用60秒
    "network": 10.0,       # 网络请求10秒
    "external_api": 30.0   # 外部API 30秒
}
```

## 故障排查

### 1. 查看错误日志

```bash
# 查看Worker错误日志
docker logs aop-orchestrator-worker | grep ERROR

# 查看特定错误类型
docker logs aop-orchestrator-worker | grep "NetworkError"
```

### 2. 监控重试情况

```bash
# 查看Prometheus重试指标
curl http://localhost:9090/api/v1/query?query=aop_agent_errors_total

# 查看任务重试率
curl http://localhost:9090/api/v1/query?query=rate(aop_tasks_total{status="retry"}[5m])
```

### 3. 检查熔断器状态

```python
# 在代码中检查熔断器状态
from error_handling import get_circuit_breaker

cb = get_circuit_breaker("database_service")
print(cb.get_state())
# 输出: {"state": "open", "failure_count": 5, ...}
```

## 测试错误处理

### 单元测试

```python
import pytest
from error_handling import RetryPolicy, with_retry, AOPError

def test_retry_policy():
    policy = RetryPolicy(max_attempts=3)
    attempts = []
    
    @with_retry(policy=policy)
    def failing_function():
        attempts.append(1)
        raise Exception("Test error")
    
    with pytest.raises(Exception):
        failing_function()
    
    assert len(attempts) == 3  # 应该重试3次

def test_error_classification():
    from error_handling import classify_error, ErrorCategory
    
    error = Exception("Connection timeout")
    category = classify_error(error)
    assert category == ErrorCategory.TIMEOUT
```

### 集成测试

```python
def test_circuit_breaker():
    from error_handling import CircuitBreaker
    
    cb = CircuitBreaker(failure_threshold=2)
    
    # 模拟失败
    for _ in range(2):
        try:
            cb.call(lambda: 1/0)  # ZeroDivisionError
        except:
            pass
    
    # 熔断器应该打开
    assert cb.state == "open"
    
    # 应该拒绝调用
    with pytest.raises(CircuitBreakerOpenError):
        cb.call(lambda: "success")
```

## 性能考虑

### 1. 重试开销

- 避免过度重试：设置合理的max_attempts
- 使用指数退避：避免雷群效应
- 添加抖动：分散重试时间

### 2. 熔断器开销

- 设置合理的失败阈值
- 监控熔断器状态
- 定期重置测试环境中的熔断器

### 3. 错误日志开销

- 使用结构化日志
- 避免在错误处理中执行复杂操作
- 限制错误上下文大小

## 相关文档

- [监控系统设置](../operations/monitoring.md)
- [高可用部署](./high-availability-setup.md)
- [API文档](../reference/api.md)