"""Agent Runtime Foundation for AOP Agents.

This package provides the runtime foundation for agents, including:
- Tool registration and execution
- Tool calling loop with LLM integration
- Execution result standardization
- Observability and metadata tracking
"""

from .runtime import (
    AgentRuntime,
    AgentRuntimeConfig,
    Tool,
    ToolRegistry,
    ToolResult,
    ExecutionResult,
    ExecutionState,
    ExecutionMetadata,
)
from .tool_loop import ToolCallingLoop, ToolLoopConfig

__all__ = [
    "AgentRuntime",
    "AgentRuntimeConfig",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "ExecutionResult",
    "ExecutionState",
    "ExecutionMetadata",
    "ToolCallingLoop",
    "ToolLoopConfig",
]
