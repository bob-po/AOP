# AOP Agent Runtime

Agent Runtime Foundation for AOP Agents, providing tool management, execution, and observability.

## Features

- **Tool Registry**: Centralized tool registration and execution
- **Tool Calling Loop**: Automated LLM + tool interaction with configurable limits
- **Execution Tracking**: Comprehensive metadata and state management
- **Error Handling**: Standardized error types and recovery strategies
- **Timeout Control**: Configurable timeouts for tool and execution
- **Observability**: Token usage, latency, and execution metrics

## Installation

```bash
pip install -e packages/agent-runtime
```

## Usage

### Basic Agent Runtime

```python
from agent_runtime import AgentRuntime, AgentRuntimeConfig, Tool, ToolResult
from llm_provider import OpenAIProvider, LLMProviderConfig

class MyAgent(AgentRuntime):
    def __init__(self):
        config = AgentRuntimeConfig(
            max_tool_iterations=10,
            tool_timeout_seconds=30.0,
            execution_timeout_seconds=300.0,
        )
        super().__init__(config)
        
        # Configure LLM provider
        llm_config = LLMProviderConfig(
            api_key="your-api-key",
            model="gpt-4o-mini",
        )
        self._llm_provider = OpenAIProvider(llm_config)
    
    def get_llm_provider(self):
        return self._llm_provider
    
    def setup_tools(self):
        # Register tools
        search_tool = Tool(
            name="search",
            description="Search the web for information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
            handler=self.search_handler,
        )
        self.register_tool(search_tool)
    
    def search_handler(self, params):
        query = params.get("query", "")
        # Implement search logic
        return ToolResult(
            success=True,
            content=f"Search results for: {query}",
            data={"results": ["result1", "result2"]},
        )
```

### Tool Calling Loop

```python
from agent_runtime.tool_loop import ToolCallingLoop, ToolLoopConfig

# Create loop configuration
loop_config = ToolLoopConfig(
    max_iterations=10,
    require_tool_confirmation=False,
    continue_on_tool_error=True,
)

# Create tool calling loop
loop = ToolCallingLoop(
    llm_provider=self.get_llm_provider(),
    agent_runtime=self,
    config=loop_config,
)

# Execute with tools
tools = self.tool_registry.to_openai_format()
result = loop.execute(
    system_prompt="You are a helpful assistant with web search capabilities.",
    user_prompt="Search for information about AI agents.",
    tools=tools,
    tool_choice="auto",
)

# Check result
if result.success:
    print(f"Response: {result.content}")
    print(f"LLM calls: {result.metadata.llm_calls}")
    print(f"Tool calls: {result.metadata.tool_calls}")
    print(f"Total tokens: {result.metadata.total_tokens}")
else:
    print(f"Execution failed: {result.metadata.error}")
```

### Tool Registration

```python
from agent_runtime import Tool, ToolResult

def calculator_handler(params):
    operation = params.get("operation")
    a = params.get("a")
    b = params.get("b")
    
    try:
        if operation == "add":
            result = a + b
        elif operation == "subtract":
            result = a - b
        elif operation == "multiply":
            result = a * b
        elif operation == "divide":
            result = a / b
        else:
            return ToolResult(
                success=False,
                content="",
                error=f"Unknown operation: {operation}",
            )
        
        return ToolResult(
            success=True,
            content=f"Result: {result}",
            data={"operation": operation, "a": a, "b": b, "result": result},
        )
    except Exception as e:
        return ToolResult(
            success=False,
            content="",
            error=str(e),
        )

calculator_tool = Tool(
    name="calculator",
    description="Perform basic arithmetic operations",
    parameters={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["add", "subtract", "multiply", "divide"],
                "description": "Operation to perform",
            },
            "a": {"type": "number", "description": "First number"},
            "b": {"type": "number", "description": "Second number"},
        },
        "required": ["operation", "a", "b"],
    },
    handler=calculator_handler,
)

self.register_tool(calculator_tool)
```

### Execution Metadata

```python
from agent_runtime import ExecutionMetadata, ExecutionState

# Create execution context
metadata = self.create_execution_context("my_agent")

# Mark as started
metadata.mark_started("my_agent")

# Execute task
try:
    result = self.execute_task(...)
    metadata.mark_completed()
except Exception as e:
    metadata.mark_failed(str(e))

# Access metadata
print(f"Execution ID: {metadata.execution_id}")
print(f"State: {metadata.state.value}")
print(f"Duration: {metadata.duration_ms}ms")
print(f"LLM calls: {metadata.llm_calls}")
print(f"Tool calls: {metadata.tool_calls}")
print(f"Total tokens: {metadata.total_tokens}")
```

## Configuration

### AgentRuntimeConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_tool_iterations` | int | 10 | Maximum tool calling iterations |
| `tool_timeout_seconds` | float | 30.0 | Timeout for individual tool execution |
| `execution_timeout_seconds` | float | 300.0 | Overall execution timeout |
| `enable_tool_calling` | bool | True | Enable tool calling functionality |
| `require_tool_confirmation` | bool | False | Require user confirmation for tools |

### ToolLoopConfig

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_iterations` | int | 10 | Maximum loop iterations |
| `require_tool_confirmation` | bool | False | Require confirmation for tool calls |
| `continue_on_tool_error` | bool | True | Continue loop on tool errors |
| `stop_on_specific_tool` | str | None | Stop when specific tool is called |

## Error Handling

The runtime provides standardized error handling:

```python
from agent_runtime import ExecutionState

result = loop.execute(...)

if result.metadata.state == ExecutionState.COMPLETED:
    print("Execution completed successfully")
elif result.metadata.state == ExecutionState.FAILED:
    print(f"Execution failed: {result.metadata.error}")
elif result.metadata.state == ExecutionState.TIMEOUT:
    print("Execution timed out")
```

## Observability

Track execution metrics:

```python
# From execution result
print(f"LLM calls: {result.metadata.llm_calls}")
print(f"Tool calls: {result.metadata.tool_calls}")
print(f"Total tokens: {result.metadata.total_tokens}")
print(f"Duration: {result.metadata.duration_ms}ms")
print(f"Execution mode: {result.metadata.execution_mode}")

# From tool result
print(f"Tool execution time: {tool_result.execution_time_ms}ms")
print(f"Tool success: {tool_result.success}")
```

## Integration with AOP Agents

The runtime is designed to integrate with existing AOP agents:

```python
# In a harness profile agent (e.g., agents/harness-agent/agent.py)
from agent_runtime import AgentRuntime, Tool, ToolResult
from llm_provider import OpenAIProvider, LLMProviderConfig

class HarnessProfileAgent(AgentRuntime):
    def __init__(self):
        # Initialize with existing config
        config = AgentRuntimeConfig(max_tool_iterations=5)
        super().__init__(config)
        
        # Setup LLM provider using existing env vars
        llm_config = LLMProviderConfig(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )
        self._llm_provider = OpenAIProvider(llm_config)
        
        # Register analysis tools
        self.setup_tools()
    
    def get_llm_provider(self):
        return self._llm_provider
```

## Harness adapters (Phase 1)

A2A shell + pluggable execution kernels (Claude CLI first):

```python
from agent_runtime.harness import create_harness_app
from agent_runtime.harness.runners import ClaudeCliRunner

app = create_harness_app(
    agent_id="claude-coder",
    runner=ClaudeCliRunner(),
    card_path="profiles/claude-coder/agent-card.json",
)
```

See [`docs/architecture/harness-migration.md`](../../docs/architecture/harness-migration.md) and `agents/harness-agent/`.

## Testing

```bash
# Install with dev dependencies
pip install -e packages/agent-runtime[dev]

# Run tests
pytest packages/agent-runtime/tests/
```

## License

MIT
