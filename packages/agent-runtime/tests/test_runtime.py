"""Unit tests for Agent Runtime using Mock Provider."""

import pytest
from agent_runtime import (
    AgentRuntime,
    AgentRuntimeConfig,
    Tool,
    ToolRegistry,
    ToolResult,
    ExecutionResult,
    ExecutionMetadata,
    ExecutionState,
)
from llm_provider import (
    MockProvider,
    LLMProviderConfig,
    ProviderType,
)


class MockAgentRuntime(AgentRuntime):
    """Mock agent runtime for testing."""
    
    def __init__(self, config=None):
        super().__init__(config)
        self._llm_provider = MockProvider(LLMProviderConfig(provider_type=ProviderType.MOCK))
    
    def get_llm_provider(self):
        return self._llm_provider


class TestToolRegistry:
    """Test suite for ToolRegistry."""
    
    def test_register_tool(self):
        """Test tool registration."""
        registry = ToolRegistry()
        
        def mock_handler(params):
            return ToolResult(success=True, content="Mock result")
        
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object", "properties": {}},
            handler=mock_handler,
        )
        
        registry.register(tool)
        
        assert registry.get("test_tool") is not None
        assert registry.get("test_tool").name == "test_tool"
    
    def test_list_tools(self):
        """Test listing tools."""
        registry = ToolRegistry()
        
        def mock_handler(params):
            return ToolResult(success=True, content="Mock result")
        
        tool1 = Tool(
            name="tool1",
            description="Tool 1",
            parameters={"type": "object"},
            handler=mock_handler,
        )
        tool2 = Tool(
            name="tool2",
            description="Tool 2",
            parameters={"type": "object"},
            handler=mock_handler,
        )
        
        registry.register(tool1)
        registry.register(tool2)
        
        tools = registry.list_tools()
        assert len(tools) == 2
    
    def test_execute_tool_success(self):
        """Test successful tool execution."""
        registry = ToolRegistry()
        
        def mock_handler(params):
            return ToolResult(success=True, content="Success", data={"result": "ok"})
        
        tool = Tool(
            name="test_tool",
            description="A test tool",
            parameters={"type": "object"},
            handler=mock_handler,
        )
        
        registry.register(tool)
        result = registry.execute("test_tool", {})
        
        assert result.success is True
        assert result.content == "Success"
        assert result.data == {"result": "ok"}
    
    def test_execute_tool_failure(self):
        """Test tool execution failure."""
        registry = ToolRegistry()
        
        def failing_handler(params):
            raise ValueError("Tool failed")
        
        tool = Tool(
            name="failing_tool",
            description="A failing tool",
            parameters={"type": "object"},
            handler=failing_handler,
        )
        
        registry.register(tool)
        result = registry.execute("failing_tool", {})
        
        assert result.success is False
        assert result.error is not None
        assert "Tool failed" in result.error
    
    def test_execute_tool_not_found(self):
        """Test executing non-existent tool."""
        registry = ToolRegistry()
        result = registry.execute("nonexistent", {})
        
        assert result.success is False
        assert "not found" in result.error.lower()
    
    def test_tool_to_openai_format(self):
        """Test tool conversion to OpenAI format."""
        tool = Tool(
            name="search",
            description="Search function",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
            },
            handler=lambda params: ToolResult(success=True, content=""),
        )
        
        openai_format = tool.to_openai_format()
        
        assert openai_format["type"] == "function"
        assert openai_format["function"]["name"] == "search"
        assert openai_format["function"]["description"] == "Search function"


class TestExecutionMetadata:
    """Test suite for ExecutionMetadata."""
    
    def test_metadata_creation(self):
        """Test metadata creation."""
        metadata = ExecutionMetadata(agent_name="test_agent")
        
        assert metadata.agent_name == "test_agent"
        assert metadata.state == ExecutionState.PENDING
        assert metadata.execution_mode == "real"
    
    def test_mark_started(self):
        """Test marking execution as started."""
        metadata = ExecutionMetadata()
        metadata.mark_started("test_agent")
        
        assert metadata.agent_name == "test_agent"
        assert metadata.state == ExecutionState.RUNNING
        assert metadata.start_time is not None
    
    def test_mark_completed(self):
        """Test marking execution as completed."""
        metadata = ExecutionMetadata()
        metadata.mark_started("test_agent")
        metadata.mark_completed()
        
        assert metadata.state == ExecutionState.COMPLETED
        assert metadata.end_time is not None
        assert metadata.duration_ms >= 0
    
    def test_mark_failed(self):
        """Test marking execution as failed."""
        metadata = ExecutionMetadata()
        metadata.mark_started("test_agent")
        metadata.mark_failed("Test error")
        
        assert metadata.state == ExecutionState.FAILED
        assert metadata.error == "Test error"
        assert metadata.end_time is not None
    
    def test_metadata_serialization(self):
        """Test metadata to dict conversion."""
        metadata = ExecutionMetadata(agent_name="test_agent")
        metadata.mark_started("test_agent")
        metadata.mark_completed()
        
        metadata_dict = metadata.to_dict()
        
        assert metadata_dict["agent_name"] == "test_agent"
        assert metadata_dict["state"] == "completed"
        assert metadata_dict["duration_ms"] >= 0


class TestAgentRuntime:
    """Test suite for AgentRuntime."""
    
    def test_runtime_creation(self):
        """Test runtime creation."""
        config = AgentRuntimeConfig(max_tool_iterations=5)
        runtime = MockAgentRuntime(config)
        
        assert runtime.config.max_tool_iterations == 5
        assert runtime.tool_registry is not None
    
    def test_register_tool(self):
        """Test tool registration in runtime."""
        runtime = MockAgentRuntime()
        
        def mock_handler(params):
            return ToolResult(success=True, content="Result")
        
        tool = Tool(
            name="test_tool",
            description="Test",
            parameters={"type": "object"},
            handler=mock_handler,
        )
        
        runtime.register_tool(tool)
        
        assert runtime.tool_registry.get("test_tool") is not None
    
    def test_execute_tool_with_timeout(self):
        """Test tool execution with timeout."""
        runtime = MockAgentRuntime()
        
        def slow_handler(params):
            import time
            time.sleep(2)  # Simulate slow operation
            return ToolResult(success=True, content="Done")
        
        tool = Tool(
            name="slow_tool",
            description="Slow tool",
            parameters={"type": "object"},
            handler=slow_handler,
        )
        
        runtime.register_tool(tool)
        
        # With short timeout, should fail
        runtime.config.tool_timeout_seconds = 0.1
        result = runtime.execute_tool("slow_tool", {})
        
        assert result.success is False
        assert "timeout" in result.error.lower()
    
    def test_create_execution_context(self):
        """Test execution context creation."""
        runtime = MockAgentRuntime()
        metadata = runtime.create_execution_context("test_agent")
        
        assert metadata.agent_name == "test_agent"
        assert metadata.state == ExecutionState.RUNNING
    
    def test_finalize_execution_success(self):
        """Test finalizing successful execution."""
        runtime = MockAgentRuntime()
        metadata = runtime.create_execution_context("test_agent")
        
        runtime.finalize_execution(metadata, success=True)
        
        assert metadata.state == ExecutionState.COMPLETED
        assert metadata.error is None
    
    def test_finalize_execution_failure(self):
        """Test finalizing failed execution."""
        runtime = MockAgentRuntime()
        metadata = runtime.create_execution_context("test_agent")
        
        runtime.finalize_execution(metadata, success=False, error="Test error")
        
        assert metadata.state == ExecutionState.FAILED
        assert metadata.error == "Test error"


class TestExecutionResult:
    """Test suite for ExecutionResult."""
    
    def test_result_creation(self):
        """Test result creation."""
        metadata = ExecutionMetadata(agent_name="test_agent")
        result = ExecutionResult(
            success=True,
            content="Test content",
            metadata=metadata,
        )
        
        assert result.success is True
        assert result.content == "Test content"
        assert result.metadata.agent_name == "test_agent"
    
    def test_result_serialization(self):
        """Test result to dict conversion."""
        metadata = ExecutionMetadata(agent_name="test_agent")
        result = ExecutionResult(
            success=True,
            content="Test content",
            data={"key": "value"},
            metadata=metadata,
        )
        
        result_dict = result.to_dict()
        
        assert result_dict["success"] is True
        assert result_dict["content"] == "Test content"
        assert result_dict["data"]["key"] == "value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
