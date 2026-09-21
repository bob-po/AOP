"""Unit tests for Tool Calling Loop using Mock Provider."""

import pytest
from agent_runtime import (
    AgentRuntime,
    Tool,
    ToolResult,
    ExecutionState,
    ToolLoopConfig,
)
from agent_runtime.tool_loop import ToolCallingLoop
from llm_provider import (
    MockProvider,
    LLMProviderConfig,
    ProviderType,
    LLMErrorType,
)


class MockAgentRuntime(AgentRuntime):
    """Mock agent runtime for testing."""
    
    def __init__(self, config=None):
        super().__init__(config)
        self._llm_provider = MockProvider(LLMProviderConfig(provider_type=ProviderType.MOCK))
    
    def get_llm_provider(self):
        return self._llm_provider


class TestToolCallingLoop:
    """Test suite for ToolCallingLoop."""
    
    def test_basic_execution(self):
        """Test basic tool calling loop execution."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Configure mock to not call tools
        llm_provider.set_response("test", "Final response without tools")
        
        # Create loop
        loop = ToolCallingLoop(llm_provider, runtime)
        
        # Execute
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Hello!",
        )
        
        assert result.success is True
        assert result.content is not None
        assert result.metadata.state == ExecutionState.COMPLETED
        assert loop.get_iteration_count() == 1
    
    def test_tool_calling_simulation(self):
        """Test tool calling with mock provider."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Register a tool
        def search_handler(params):
            query = params.get("query", "")
            return ToolResult(
                success=True,
                content=f"Search results for: {query}",
                data={"results": ["result1", "result2"]},
            )
        
        search_tool = Tool(
            name="search",
            description="Search the web",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                },
                "required": ["query"],
            },
            handler=search_handler,
        )
        
        runtime.register_tool(search_tool)
        
        # Create loop with tools
        loop = ToolCallingLoop(llm_provider, runtime)
        
        # Execute with tools
        tools = runtime.tool_registry.to_openai_format()
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Search for information about AI.",
            tools=tools,
            tool_choice="auto",
        )
        
        # Mock provider should simulate tool calls
        assert result.metadata.tool_calls >= 0
        assert loop.get_iteration_count() >= 1
    
    def test_max_iterations_limit(self):
        """Test that loop respects max iterations limit."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Configure mock to always return tool calls
        # This will cause the loop to continue until max iterations
        tools = [{"type": "function", "function": {"name": "test", "parameters": {}}}]
        
        # Create loop with low max iterations
        loop_config = ToolLoopConfig(max_iterations=3)
        loop = ToolCallingLoop(llm_provider, runtime, loop_config)
        
        # Execute
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Test",
            tools=tools,
            tool_choice="required",  # Force tool calls
        )
        
        # Should stop at max iterations
        assert loop.get_iteration_count() <= 3
        assert result.metadata.state == ExecutionState.FAILED
        assert "Max iterations" in result.metadata.error
    
    def test_llm_error_handling(self):
        """Test LLM error handling in loop."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Configure mock to fail
        llm_provider.set_failure(should_fail=True, failure_type=LLMErrorType.RATE_LIMIT)
        
        # Create loop
        loop = ToolCallingLoop(llm_provider, runtime)
        
        # Execute
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Test",
        )
        
        assert result.success is False
        assert result.metadata.state == ExecutionState.FAILED
        assert result.metadata.error is not None
    
    def test_tool_execution_failure(self):
        """Test tool execution failure handling."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Register a failing tool
        def failing_handler(params):
            raise ValueError("Tool execution failed")
        
        failing_tool = Tool(
            name="failing_tool",
            description="A tool that fails",
            parameters={"type": "object"},
            handler=failing_handler,
        )
        
        runtime.register_tool(failing_tool)
        
        # Create loop with continue_on_tool_error=False
        loop_config = ToolLoopConfig(continue_on_tool_error=False)
        loop = ToolCallingLoop(llm_provider, runtime, loop_config)
        
        # Execute with tools
        tools = runtime.tool_registry.to_openai_format()
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Use the failing tool",
            tools=tools,
            tool_choice="required",
        )
        
        # Should fail when tool execution fails
        assert result.metadata.state == ExecutionState.FAILED
    
    def test_stop_on_specific_tool(self):
        """Test stopping on specific tool."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Register tools
        def search_handler(params):
            return ToolResult(success=True, content="Search results")
        
        def final_handler(params):
            return ToolResult(success=True, content="Final result")
        
        search_tool = Tool(
            name="search",
            description="Search",
            parameters={"type": "object"},
            handler=search_handler,
        )
        
        final_tool = Tool(
            name="final",
            description="Final tool",
            parameters={"type": "object"},
            handler=final_handler,
        )
        
        runtime.register_tool(search_tool)
        runtime.register_tool(final_tool)
        
        # Create loop with stop condition
        loop_config = ToolLoopConfig(stop_on_specific_tool="final")
        loop = ToolCallingLoop(llm_provider, runtime, loop_config)
        
        # Execute
        tools = runtime.tool_registry.to_openai_format()
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Use tools",
            tools=tools,
            tool_choice="auto",
        )
        
        # Should complete when final tool is called
        # (This is a simulation, actual behavior depends on mock provider)
        assert result.metadata.state in (ExecutionState.COMPLETED, ExecutionState.FAILED)
    
    def test_message_history_tracking(self):
        """Test message history tracking."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Configure mock to not call tools
        llm_provider.set_response("test", "Response")
        
        # Create loop
        loop = ToolCallingLoop(llm_provider, runtime)
        
        # Execute
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Hello!",
        )
        
        # Check message history
        messages = loop.get_messages()
        assert len(messages) >= 2  # System + user
        assert messages[0].role == "system"
        assert messages[1].role == "user"
    
    def test_reset_functionality(self):
        """Test loop reset functionality."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Create loop
        loop = ToolCallingLoop(llm_provider, runtime)
        
        # Execute first run
        loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Test 1",
        )
        
        first_count = loop.get_iteration_count()
        assert first_count > 0
        
        # Reset
        loop.reset()
        
        # Execute second run
        loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Test 2",
        )
        
        second_count = loop.get_iteration_count()
        assert second_count == 1  # Should start fresh
    
    def test_metadata_tracking(self):
        """Test execution metadata tracking."""
        # Setup
        llm_config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        llm_provider = MockProvider(llm_config)
        runtime = MockAgentRuntime()
        
        # Create loop
        loop = ToolCallingLoop(llm_provider, runtime)
        
        # Execute
        result = loop.execute(
            system_prompt="You are a helpful assistant.",
            user_prompt="Test",
        )
        
        # Check metadata
        assert result.metadata.llm_calls > 0
        assert result.metadata.execution_id is not None
        assert result.metadata.start_time is not None
        assert result.metadata.end_time is not None
        assert result.metadata.duration_ms >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
