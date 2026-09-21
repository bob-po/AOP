# Phase 37.2 启用指南

## 问题分析

你发现agents还在使用legacy模式，没有调用LLM，这是因为需要设置环境变量来启用Phase 37.2的增强模式。

## 解决方案

### 1. 设置LLM API密钥

首先需要设置OpenAI API密钥来启用LLM功能：

```bash
# Windows PowerShell
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_BASE_URL="https://api.openai.com/v1"  # 可选，默认为OpenAI
$env:OPENAI_MODEL="gpt-4o-mini"  # 可选，默认为gpt-4o-mini

# 或者使用DeepSeek
$env:OPENAI_BASE_URL="https://api.deepseek.com/v1"
$env:OPENAI_MODEL="deepseek-chat"
```

### 2. 安装LLM Provider依赖

Phase 37.2的agents需要新的依赖包：

```bash
cd C:\Users\guojiayang\Desktop\work\cursor\AOP
pip install -e packages/llm-provider
pip install -e packages/agent-runtime
```

### 3. 启用增强模式

现在更新后的启动脚本会自动设置以下环境变量：

- `SEARCH_USE_ENHANCED=true` - 启用Search Agent的增强模式
- `ANALYSIS_USE_ENHANCED=true` - 启用Analysis Agent的增强模式
- `REPORT_USE_ENHANCED=true` - 启用Report Agent的增强模式
- `RAG_USE_ENHANCED=true` - 启用RAG Agent的增强模式

### 4. 重新启动agents

现在重新启动agents，它们会自动使用增强模式：

```bash
python scripts/start_and_register_agents.py
```

## 验证LLM调用

### 检查agent日志

查看agent日志文件确认LLM是否被调用：

```bash
# Search Agent日志
type agents\search-agent\.uvicorn-8001.log

# Analysis Agent日志
type agents\analysis-agent\.uvicorn-8004.log

# Report Agent日志
type agents\report-agent\.uvicorn-8003.log
```

你应该看到类似这样的日志：
```
[Search Agent] LLM provider initialized: gpt-4o-mini
[Analysis Agent] Enhanced analysis completed: 150 tokens, 1200ms
[Report Agent] Report generated: 2000 tokens, 2500ms
```

### 手动测试单个agent

也可以手动测试单个agent来验证LLM集成：

```bash
# 测试Search Agent
cd agents\search-agent
python test_enhanced.py

# 测试Analysis Agent  
cd agents\analysis-agent
python test_enhanced.py

# 测试Report Agent
cd agents\report-agent
python test_enhanced.py
```

## 当前状态分析

### 为什么之前没有调用LLM？

1. **环境变量未设置**: agents默认使用legacy模式以保持向后兼容
2. **依赖未安装**: 增强模块需要`llm-provider`和`agent-runtime`包
3. **API密钥缺失**: 没有设置`OPENAI_API_KEY`时agents会使用deterministic fallback

### Phase 37.2的渐进式启用策略

- **Analysis Agent**: `ANALYSIS_USE_ENHANCED=true` (默认启用)
- **Report Agent**: `REPORT_USE_ENHANCED=true` (默认启用)  
- **Search Agent**: `SEARCH_USE_ENHANCED=true` (需要显式启用)
- **RAG Agent**: `RAG_USE_ENHANCED=true` (需要显式启用)

这种策略确保了向后兼容性，同时允许逐步启用新功能。

## 完整启用步骤

```bash
# 1. 设置API密钥
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"

# 2. 安装依赖
pip install -e packages/llm-provider
pip install -e packages/agent-runtime

# 3. 重新启动agents (现在会自动设置增强模式环境变量)
python scripts/start_and_register_agents.py

# 4. 测试一个完整任务
# 通过Console或API创建一个测试任务
```

## 预期效果对比

### 启用前 (Legacy模式)
- Search Agent: 使用Wikipedia API，直接返回结果
- Analysis Agent: 使用deterministic fallback或直接OpenAI SDK
- Report Agent: 模板拼接生成报告
- RAG Agent: 纯TF-IDF搜索，无LLM增强

### 启用后 (Enhanced模式)
- Search Agent: LLM工具调用loop，智能查询理解
- Analysis Agent: 统一LLM Provider，带token/latency跟踪
- Report Agent: LLM从结构化数据合成报告
- RAG Agent: 租户隔离+LLM答案合成+引用追踪

## 故障排查

### 如果仍然没有调用LLM

1. **检查依赖安装**:
```bash
pip show aop-llm-provider
pip show aop-agent-runtime
```

2. **检查环境变量**:
```bash
echo $env:OPENAI_API_KEY
echo $env:ANALYSIS_USE_ENHANCED
```

3. **检查agent日志**: 查看是否有LLM provider初始化日志

4. **手动测试**: 运行`test_enhanced.py`验证模块是否正常工作

### 如果API调用失败

1. **检查网络连接**: 确保能访问OpenAI API
2. **检查API密钥**: 验证密钥是否有效
3. **检查base_url**: 确认API endpoint配置正确
4. **查看错误日志**: agent日志会显示具体的错误信息

## 配置示例

### 使用OpenAI
```bash
$env:OPENAI_API_KEY="sk-proj-..."
$env:OPENAI_BASE_URL="https://api.openai.com/v1"
$env:OPENAI_MODEL="gpt-4o-mini"
```

### 使用DeepSeek
```bash
$env:OPENAI_API_KEY="sk-..."
$env:OPENAI_BASE_URL="https://api.deepseek.com/v1"
$env:OPENAI_MODEL="deepseek-chat"
```

### 使用其他OpenAI兼容API
```bash
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_BASE_URL="https://your-api-endpoint/v1"
$env:OPENAI_MODEL="your-model-name"
```

现在重新启动agents后，你应该能看到真实的LLM调用和增强的功能效果。
