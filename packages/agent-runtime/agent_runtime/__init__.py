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
from .collaboration import (
    A2ACollaborationRuntime,
    CallContext,
    DelegationResult,
    GovernanceConfig,
    GovernanceError,
    RECURSION_LIMIT_EXCEEDED,
    CYCLE_DETECTED,
    CALL_LIMIT_EXCEEDED,
    NO_AGENT_AVAILABLE,
)
from .a2a_server import (
    extract_lineage,
    inbound_context,
    jsonrpc_result,
    jsonrpc_error,
    cancel_task,
    subscribe_events,
    notify_callback,
    handle_control_method,
)
from .agent_collab import AgentCollaborator

# Harness adapters (optional FastAPI at create_harness_app time)
from .harness.protocol import (
    SCHEMA_VERSION,
    HarnessEvent,
    HarnessEventType,
    HarnessResult,
    HarnessStatus,
    TokenUsage,
)

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
    "A2ACollaborationRuntime",
    "CallContext",
    "DelegationResult",
    "GovernanceConfig",
    "GovernanceError",
    "RECURSION_LIMIT_EXCEEDED",
    "CYCLE_DETECTED",
    "CALL_LIMIT_EXCEEDED",
    "NO_AGENT_AVAILABLE",
    "extract_lineage",
    "inbound_context",
    "jsonrpc_result",
    "jsonrpc_error",
    "cancel_task",
    "subscribe_events",
    "notify_callback",
    "handle_control_method",
    "AgentCollaborator",
    "SCHEMA_VERSION",
    "HarnessEvent",
    "HarnessEventType",
    "HarnessResult",
    "HarnessStatus",
    "TokenUsage",
]
