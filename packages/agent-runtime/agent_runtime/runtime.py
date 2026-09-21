"""Core Agent Runtime with tool management and execution."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Dict, List
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)


class ExecutionState(Enum):
    """States of agent execution."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass
class ExecutionMetadata:
    """Metadata for agent execution."""
    execution_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    agent_name: str = ""
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: Optional[str] = None
    duration_ms: int = 0
    state: ExecutionState = ExecutionState.PENDING
    llm_calls: int = 0
    tool_calls: int = 0
    total_tokens: int = 0
    error: Optional[str] = None
    execution_mode: str = "real"  # "real", "mock", "fallback"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "agent_name": self.agent_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "state": self.state.value,
            "llm_calls": self.llm_calls,
            "tool_calls": self.tool_calls,
            "total_tokens": self.total_tokens,
            "error": self.error,
            "execution_mode": self.execution_mode,
        }
    
    def mark_started(self, agent_name: str) -> None:
        """Mark execution as started."""
        self.agent_name = agent_name
        self.state = ExecutionState.RUNNING
        self.start_time = datetime.now(timezone.utc).isoformat()
    
    def mark_completed(self) -> None:
        """Mark execution as completed."""
        self.state = ExecutionState.COMPLETED
        self.end_time = datetime.now(timezone.utc).isoformat()
        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time)
            self.duration_ms = int((end - start).total_seconds() * 1000)
    
    def mark_failed(self, error: str) -> None:
        """Mark execution as failed."""
        self.state = ExecutionState.FAILED
        self.error = error
        self.end_time = datetime.now(timezone.utc).isoformat()
        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time)
            self.duration_ms = int((end - start).total_seconds() * 1000)
    
    def mark_timeout(self) -> None:
        """Mark execution as timed out."""
        self.state = ExecutionState.TIMEOUT
        self.error = "Execution timeout"
        self.end_time = datetime.now(timezone.utc).isoformat()
        if self.start_time:
            start = datetime.fromisoformat(self.start_time)
            end = datetime.fromisoformat(self.end_time)
            self.duration_ms = int((end - start).total_seconds() * 1000)


@dataclass
class ToolResult:
    """Result from tool execution."""
    success: bool
    content: str
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "data": self.data,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
        }


@dataclass
class Tool:
    """Represents a callable tool for agent use."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], ToolResult]
    
    def to_openai_format(self) -> dict[str, Any]:
        """Convert tool to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry for managing available tools."""
    
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
    
    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")
    
    def get(self, name: str) -> Optional[Tool]:
        """Get a tool by name."""
        return self._tools.get(name)
    
    def list_tools(self) -> List[Tool]:
        """List all registered tools."""
        return list(self._tools.values())
    
    def to_openai_format(self) -> List[dict[str, Any]]:
        """Convert all tools to OpenAI format."""
        return [tool.to_openai_format() for tool in self._tools.values()]
    
    def execute(self, name: str, parameters: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        tool = self.get(name)
        if not tool:
            return ToolResult(
                success=False,
                content="",
                error=f"Tool not found: {name}",
            )
        
        try:
            start_time = time.time()
            result = tool.handler(parameters)
            execution_time_ms = int((time.time() - start_time) * 1000)
            result.execution_time_ms = execution_time_ms
            return result
        except Exception as e:
            logger.error(f"Tool execution failed for {name}: {str(e)}")
            return ToolResult(
                success=False,
                content="",
                error=str(e),
            )


@dataclass
class ExecutionResult:
    """Standardized result from agent execution."""
    success: bool
    content: str
    data: Optional[dict[str, Any]] = None
    metadata: ExecutionMetadata = field(default_factory=ExecutionMetadata)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "data": self.data,
            "metadata": self.metadata.to_dict(),
        }


@dataclass
class AgentRuntimeConfig:
    """Configuration for agent runtime."""
    max_tool_iterations: int = 10
    tool_timeout_seconds: float = 30.0
    execution_timeout_seconds: float = 300.0
    enable_tool_calling: bool = True
    require_tool_confirmation: bool = False


class AgentRuntime(ABC):
    """Abstract base class for agent runtime with tool support."""
    
    def __init__(self, config: Optional[AgentRuntimeConfig] = None):
        self.config = config or AgentRuntimeConfig()
        self.tool_registry = ToolRegistry()
        self._metadata = ExecutionMetadata()
    
    @abstractmethod
    def get_llm_provider(self):
        """Get the LLM provider for this agent."""
        pass
    
    def register_tool(self, tool: Tool) -> None:
        """Register a tool for agent use."""
        self.tool_registry.register(tool)
    
    def execute_tool(self, name: str, parameters: dict[str, Any]) -> ToolResult:
        """Execute a tool with timeout and error handling."""
        import threading
        import queue
        
        def run_tool():
            return self.tool_registry.execute(name, parameters)
        
        try:
            # Use threading for timeout (cross-platform)
            result_queue = queue.Queue()
            thread = threading.Thread(target=lambda: result_queue.put(run_tool()))
            thread.daemon = True
            thread.start()
            thread.join(timeout=self.config.tool_timeout_seconds)
            
            if thread.is_alive():
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Tool execution timeout: {name}",
                )
            
            result = result_queue.get_nowait()
            return result
        except Exception as e:
            logger.error(f"Tool execution error for {name}: {str(e)}")
            return ToolResult(
                success=False,
                content="",
                error=str(e),
            )
    
    def create_execution_context(self, agent_name: str) -> ExecutionMetadata:
        """Create a new execution context."""
        metadata = ExecutionMetadata(agent_name=agent_name)
        metadata.mark_started(agent_name)
        return metadata
    
    def finalize_execution(self, metadata: ExecutionMetadata, success: bool, error: Optional[str] = None) -> None:
        """Finalize execution with appropriate state."""
        if success:
            metadata.mark_completed()
        else:
            metadata.mark_failed(error or "Unknown error")


__all__ = [
    "ExecutionState",
    "ExecutionMetadata",
    "ToolResult",
    "Tool",
    "ToolRegistry",
    "ExecutionResult",
    "AgentRuntimeConfig",
    "AgentRuntime",
]
