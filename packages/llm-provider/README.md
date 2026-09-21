# AOP LLM Provider

Unified LLM Provider interface for AOP Agents, supporting multiple providers with consistent error handling, observability, and tool calling capabilities.

## Features

- **Multi-Provider Support**: OpenAI-compatible providers (OpenAI, DeepSeek, etc.)
- **Tool Calling**: Native support for function calling with automatic loop management
- **Error Classification**: Standardized error types for handling and observability
- **Observability**: Token usage tracking, latency metrics, and request metadata
- **Retry Logic**: Configurable retry with exponential backoff
- **Mock Provider**: Testing without real API calls

## Installation

```bash
pip install -e packages/llm-provider
```

## Usage

### Basic Usage

```python
from llm_provider import OpenAIProvider, LLMProviderConfig, ProviderType

# Configure provider
config = LLMProviderConfig(
    provider_type=ProviderType.OPENAI,
    api_key="your-api-key",
    base_url="https://api.openai.com/v1",  # or DeepSeek endpoint
    model="gpt-4o-mini",
    timeout=60.0,
    max_retries=3,
)

# Create provider
provider = OpenAIProvider(config)

# Make request
request = provider.create_request(
    messages=[
        provider.create_system_message("You are a helpful assistant."),
        provider.create_user_message("Hello!"),
    ],
)

response = provider.chat_completion(request)
print(f"Response: {response.content}")
print(f"Tokens used: {response.usage}")
print(f"Latency: {response.latency_ms}ms")
```

### Tool Calling

```python
from llm_provider import OpenAIProvider, LLMProviderConfig

# Define tools
tools = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    }
]

# Request with tools
request = provider.create_request(
    messages=[
        provider.create_system_message("You are a helpful assistant."),
        provider.create_user_message("Search for information about AI agents."),
    ],
    tools=tools,
    tool_choice="auto",
)

response = provider.chat_completion(request)
if response.tool_calls:
    print(f"Tool calls: {response.tool_calls}")
```

### Structured Output

```python
# Request JSON response
request = provider.create_request(
    messages=[
        provider.create_system_message("You are a data analyst."),
        provider.create_user_message("Analyze this data."),
    ],
    response_format={"type": "json_object"},
)

response = provider.chat_completion(request)
```

### Mock Provider for Testing

```python
from llm_provider import MockProvider, LLMProviderConfig, ProviderType

# Create mock provider
config = LLMProviderConfig(provider_type=ProviderType.MOCK)
mock_provider = MockProvider(config)

# Set canned response
mock_provider.set_response("test", "Mock response for test")

# Configure failure
mock_provider.set_failure(should_fail=True, failure_type=LLMErrorType.RATE_LIMIT)

# Use like normal provider
request = mock_provider.create_request(
    messages=[mock_provider.create_user_message("test")],
)
response = mock_provider.chat_completion(request)
```

## Configuration

### Environment Variables

```bash
# OpenAI Configuration
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini

# DeepSeek Configuration
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat
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

## Error Handling

The provider classifies errors into standard types:

- `AUTHENTICATION`: Invalid API key or credentials
- `RATE_LIMIT`: Rate limit exceeded (429)
- `TIMEOUT`: Request timeout
- `NETWORK`: Network connectivity issues
- `VALIDATION`: Invalid request parameters (400)
- `PROVIDER`: Provider-side errors (500, 502, 503)
- `UNKNOWN`: Unclassified errors

```python
from llm_provider import LLMError, LLMErrorType

try:
    response = provider.chat_completion(request)
except LLMError as e:
    if e.error_type == LLMErrorType.RATE_LIMIT:
        # Handle rate limiting
        print("Rate limited, please wait")
    elif e.error_type == LLMErrorType.AUTHENTICATION:
        # Handle authentication errors
        print("Invalid API key")
    else:
        # Handle other errors
        print(f"Error: {e.to_dict()}")
```

## Observability

Each response includes comprehensive metadata:

```python
response = provider.chat_completion(request)

print(f"Model: {response.model}")
print(f"Finish reason: {response.finish_reason}")
print(f"Usage: {response.usage}")
print(f"Latency: {response.latency_ms}ms")
print(f"Timestamp: {response.timestamp}")
print(f"Provider: {response.provider}")
```

## Integration with Agent Runtime

See `packages/agent-runtime` for integration with tool calling loops and agent execution.

## Testing

```bash
# Install with dev dependencies
pip install -e packages/llm-provider[dev]

# Run tests
pytest packages/llm-provider/tests/
```

## License

MIT
