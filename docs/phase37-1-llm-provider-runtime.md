# Phase 37.1 — Unified LLM Provider & Agent Runtime Foundation

## Overview

Phase 37.1 establishes a unified LLM calling layer and agent runtime foundation for AOP agents, providing the infrastructure needed for real Search, RAG, Analysis, Report, and other agents to execute with actual LLM capabilities.

## Implementation Summary

### 1. Unified LLM Provider (`packages/llm-provider`)

**Components:**
- `provider.py`: Core interfaces and data structures
- `openai_provider.py`: OpenAI-compatible provider implementation
- `mock_provider.py`: Mock provider for testing

**Key Features:**
- Multi-provider support (OpenAI, DeepSeek, other OpenAI-compatible APIs)
- Standardized error classification (authentication, rate limit, timeout, network, validation, provider)
- Built-in retry logic with exponential backoff
- Comprehensive observability (token usage, latency, metadata)
- Tool calling support with structured output
- Mock provider for testing without real API calls

**Usage Example:**
```python
from llm_provider import OpenAIProvider, LLMProviderConfig, ProviderType

config = LLMProviderConfig(
    provider_type=ProviderType.OPENAI,
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    timeout=60.0,
    max_retries=3,
)

provider = OpenAIProvider(config)
request = provider.create_request(
    messages=[
        provider.create_system_message("You are a helpful assistant."),
        provider.create_user_message("Hello!"),
    ],
)
response = provider.chat_completion(request)
```

### 2. Agent Runtime Foundation (`packages/agent-runtime`)

**Components:**
- `runtime.py`: Core runtime with tool registry and execution management
- `tool_loop.py`: Tool calling loop with LLM integration

**Key Features:**
- Tool registration and execution with timeout control
- Automated tool calling loop with configurable iteration limits
- Standardized execution metadata and state tracking
- Error handling and recovery strategies
- Integration with LLM provider for seamless tool interactions

**Usage Example:**
```python
from agent_runtime import AgentRuntime, Tool, ToolResult
from agent_runtime.tool_loop import ToolCallingLoop

class MyAgent(AgentRuntime):
    def __init__(self):
        super().__init__()
        self._llm_provider = OpenAIProvider(config)
    
    def get_llm_provider(self):
        return self._llm_provider
    
    def setup_tools(self):
        search_tool = Tool(
            name="search",
            description="Search the web",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=self.search_handler,
        )
        self.register_tool(search_tool)
    
    def search_handler(self, params):
        return ToolResult(success=True, content="Search results", data={...})

# Execute with tool calling
loop = ToolCallingLoop(self._llm_provider, self)
result = loop.execute(
    system_prompt="You are a helpful assistant.",
    user_prompt="Search for information about AI.",
    tools=self.tool_registry.to_openai_format(),
    tool_choice="auto",
)
```

## Current Agent Mock/Stub Inventory

Based on the audit, here's the current state of agent implementations:

### Agents Using Real External Calls
- **Search Agent** (8001): Real search via `run_search()`, no LLM
- **RAG Agent** (8002): TF-IDF vector search, no LLM
- **Code Agent** (8007): AST-safe sandboxed evaluator, no external calls
- **Browser Agent** (8008): Playwright or stub, no LLM

### Agents Using LLM via context.py
- **Analysis Agent** (8004): Uses OpenAI LLM via `context.py` if `OPENAI_API_KEY` set, else deterministic fallback
- **Report Agent** (8003): Uses OpenAI LLM via `context.py` if `OPENAI_API_KEY` set, else deterministic fallback

### Agents Using Stub/Mock Implementations
- **Image Agent** (8005): Stub SVG generator, no real LLM
- **Video Agent** (8006): Stub storyboard generator, no real LLM

### Legacy LLM Usage
The existing `context.py` module in `analysis-agent` and `report-agent` provides basic OpenAI integration:
- Direct environment variable access (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`)
- Simple chat completion with optional JSON mode
- No retry logic, error classification, or observability
- No tool calling support
- Hardcoded OpenAI SDK usage

## Migration Path

### Phase 37.1 Foundation (Current)
- ✅ Unified LLM Provider interface
- ✅ Agent Runtime foundation
- ✅ Mock Provider for testing
- ✅ Unit tests with Mock Provider
- ✅ Optional integration tests with real Provider

### Phase 37.2 Agent Migration (Next)
- Migrate `analysis-agent` to use new LLM Provider
- Migrate `report-agent` to use new LLM Provider
- Add tool calling capabilities to agents
- Integrate with existing A2A protocol

### Phase 37.3 Enhanced Capabilities (Future)
- Add real LLM capabilities to stub agents (image, video)
- Implement advanced tool calling scenarios
- Add streaming support
- Implement cost tracking and budget controls

## Testing Strategy

### Unit Tests (Mock Provider)
- `packages/llm-provider/tests/test_provider.py`: 305 lines of comprehensive unit tests
- `packages/agent-runtime/tests/test_runtime.py`: 321 lines of runtime tests
- `packages/agent-runtime/tests/test_tool_loop.py`: 310 lines of tool loop tests

**Coverage:**
- Basic request/response handling
- Tool calling simulation
- Error handling and classification
- Timeout and retry logic
- Message serialization/deserialization
- Execution metadata tracking
- Tool registration and execution

### Integration Tests (Real Provider)
- `packages/llm-provider/tests/test_integration.py`: 305 lines of integration tests
- Requires `OPENAI_API_KEY` environment variable
- Tests real API calls, structured output, tool calling
- Validates observability metadata
- Tests custom base URLs (DeepSeek, etc.)

**Running Tests:**
```bash
# Unit tests (no API key required)
pip install -e packages/llm-provider[dev]
pytest packages/llm-provider/tests/test_provider.py

pip install -e packages/agent-runtime[dev]
pytest packages/agent-runtime/tests/test_runtime.py
pytest packages/agent-runtime/tests/test_tool_loop.py

# Integration tests (requires API key)
OPENAI_API_KEY=sk-... pytest packages/llm-provider/tests/test_integration.py
```

## Configuration

### Environment Variables
```bash
# OpenAI Configuration
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# DeepSeek Configuration
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
```

### Configuration Options
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `provider_type` | ProviderType | OPENAI | Provider type |
| `api_key` | str | None | API key (never logged) |
| `base_url` | str | None | Custom base URL |
| `model` | str | "gpt-4o-mini" | Model name |
| `timeout` | float | 60.0 | Request timeout (seconds) |
| `max_retries` | int | 3 | Maximum retry attempts |
| `retry_delay` | float | 1.0 | Initial retry delay (seconds) |
| `temperature` | float | 0.7 | Sampling temperature |
| `max_tokens` | int | None | Maximum tokens to generate |

## Observability

### Execution Metadata
Each execution includes comprehensive metadata:
- `execution_id`: Unique identifier for the execution
- `agent_name`: Name of the agent
- `start_time`/`end_time`: Execution timestamps
- `duration_ms`: Total execution duration
- `state`: Execution state (pending, running, completed, failed, timeout, cancelled)
- `llm_calls`: Number of LLM API calls
- `tool_calls`: Number of tool executions
- `total_tokens`: Total tokens consumed
- `error`: Error message if failed
- `execution_mode`: Execution mode (real, mock, fallback)

### Response Metadata
Each LLM response includes:
- `model`: Model used
- `finish_reason`: Reason for completion (stop, length, tool_calls, etc.)
- `usage`: Token usage breakdown (prompt, completion, total)
- `latency_ms`: Request latency in milliseconds
- `timestamp`: Response timestamp
- `provider`: Provider name

## Error Handling

### Error Classification
Errors are classified into standard types:
- `AUTHENTICATION`: Invalid API key or credentials
- `RATE_LIMIT`: Rate limit exceeded (429)
- `TIMEOUT`: Request timeout
- `NETWORK`: Network connectivity issues
- `VALIDATION`: Invalid request parameters (400)
- `PROVIDER`: Provider-side errors (500, 502, 503)
- `UNKNOWN`: Unclassified errors

### Retry Logic
- Automatic retry with exponential backoff
- Configurable max retries and delay
- Smart error classification (no retry on auth/validation errors)
- Detailed logging of retry attempts

## Compatibility with Existing Architecture

### A2A Protocol Compatibility
- ✅ No changes to A2A protocol
- ✅ Existing A2A executor unchanged
- ✅ Agent cards remain compatible
- ✅ Message/send protocol unchanged

### Phase 36 Idempotency Compatibility
- ✅ Existing idempotency mechanism preserved
- ✅ Agent-side idempotency cache unchanged
- ✅ Request tracking service integration points preserved
- ✅ No breaking changes to idempotency keys

### Existing Agent Compatibility
- ✅ Current agents continue to work unchanged
- ✅ Legacy `context.py` module still functional
- ✅ Gradual migration path available
- ✅ No forced upgrades required

## Installation

```bash
# Install LLM Provider
pip install -e packages/llm-provider

# Install Agent Runtime
pip install -e packages/agent-runtime

# Install with dev dependencies
pip install -e packages/llm-provider[dev]
pip install -e packages/agent-runtime[dev]
```

## Dependencies

### LLM Provider
- `openai>=1.0.0`: OpenAI Python SDK

### Agent Runtime
- `aop-llm-provider>=0.1.0`: Unified LLM Provider

## Security Considerations

### API Key Management
- API keys are never logged or exposed in error messages
- Configuration methods mask API keys in output
- Environment variable-based configuration recommended
- No hardcoded credentials in code

### Tool Execution Security
- Tool execution with configurable timeouts
- Permission checks before tool execution
- Error isolation between tool executions
- No arbitrary code execution in tool handlers

## Performance Considerations

### Latency
- LLM requests include timeout configuration
- Tool execution has separate timeout controls
- Overall execution timeout available
- Latency metrics tracked for observability

### Resource Usage
- Token usage tracked for cost monitoring
- Tool execution limits prevent runaway processes
- Configurable iteration limits for tool calling loops
- Memory efficient message history management

## Troubleshooting

### Common Issues

**Issue**: Import errors for `llm_provider` or `agent_runtime`
**Solution**: Ensure packages are installed: `pip install -e packages/llm-provider packages/agent-runtime`

**Issue**: Authentication errors with real API
**Solution**: Check `OPENAI_API_KEY` environment variable and verify API key validity

**Issue**: Timeout errors
**Solution**: Increase `timeout` configuration or check network connectivity

**Issue**: Rate limiting
**Solution**: Implement exponential backoff (built-in) or reduce request frequency

## Future Enhancements

### Planned Features
- Streaming support for real-time responses
- Cost tracking and budget controls
- Advanced tool calling scenarios (parallel execution)
- Multi-modal support (images, audio)
- Provider-specific optimizations
- Caching layer for common requests

### Extension Points
- Custom provider implementations
- Custom tool handlers
- Custom error classification
- Custom retry strategies
- Custom observability hooks

## Documentation

- **LLM Provider**: `packages/llm-provider/README.md`
- **Agent Runtime**: `packages/agent-runtime/README.md`
- **API Documentation**: Inline docstrings in all modules
- **Examples**: See test files for usage examples

## Support and Contributing

For issues, questions, or contributions:
1. Check existing documentation
2. Review test files for examples
3. Ensure all tests pass before submitting changes
4. Follow existing code style and patterns

## Conclusion

Phase 37.1 successfully establishes the foundation for unified LLM provider integration and agent runtime capabilities in AOP. The implementation:

- ✅ Provides a clean, extensible LLM provider interface
- ✅ Supports multiple OpenAI-compatible providers
- ✅ Includes comprehensive testing with mock and real providers
- ✅ Maintains full compatibility with existing A2A protocol and Phase 36
- ✅ Establishes clear migration path for existing agents
- ✅ Includes detailed documentation and examples

The foundation is now ready for Phase 37.2, which will migrate existing agents to use the new unified LLM provider and implement real tool calling capabilities.
