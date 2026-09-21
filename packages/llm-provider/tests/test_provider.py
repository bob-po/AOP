"""Unit tests for LLM Provider using Mock Provider."""

import pytest
from llm_provider import (
    MockProvider,
    LLMProviderConfig,
    LLMRequest,
    LLMResponse,
    LLMMessage,
    LLMToolCall,
    LLMError,
    LLMErrorType,
    ProviderType,
)


class TestMockProvider:
    """Test suite for MockProvider."""
    
    def test_basic_request(self):
        """Test basic chat completion."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("Hello!"),
            ],
        )
        
        response = provider.chat_completion(request)
        
        assert response.content is not None
        assert response.model == request.model
        assert response.finish_reason == "stop"
        assert response.provider == "mock"
        assert response.latency_ms >= 0
    
    def test_canned_response(self):
        """Test canned response functionality."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        provider.set_response("test key", "Custom response")
        
        request = provider.create_request(
            messages=[provider.create_user_message("test key")],
        )
        
        response = provider.chat_completion(request)
        assert "Custom response" in response.content
    
    def test_tool_calling(self):
        """Test tool calling simulation."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Search function",
                    "parameters": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                },
            }
        ]
        
        request = provider.create_request(
            messages=[provider.create_user_message("Search for something")],
            tools=tools,
            tool_choice="auto",
        )
        
        response = provider.chat_completion(request)
        
        assert response.tool_calls is not None
        assert len(response.tool_calls) > 0
        assert response.tool_calls[0].function is not None
        assert response.tool_calls[0].function["name"] == "search"
    
    def test_error_simulation(self):
        """Test error simulation."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        provider.set_failure(should_fail=True, failure_type=LLMErrorType.RATE_LIMIT)
        
        request = provider.create_request(
            messages=[provider.create_user_message("test")],
        )
        
        with pytest.raises(LLMError) as exc_info:
            provider.chat_completion(request)
        
        assert exc_info.value.error_type == LLMErrorType.RATE_LIMIT
        assert exc_info.value.provider == "mock"
    
    def test_latency_simulation(self):
        """Test latency simulation."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        provider.set_latency(100)  # 100ms
        
        request = provider.create_request(
            messages=[provider.create_user_message("test")],
        )
        
        response = provider.chat_completion(request)
        assert response.latency_ms >= 100
    
    def test_health_check(self):
        """Test health check."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        assert provider.health_check() is True
    
    def test_call_counting(self):
        """Test call counting."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        request = provider.create_request(
            messages=[provider.create_user_message("test")],
        )
        
        assert provider.get_call_count() == 0
        
        provider.chat_completion(request)
        assert provider.get_call_count() == 1
        
        provider.chat_completion(request)
        assert provider.get_call_count() == 2
        
        provider.reset()
        assert provider.get_call_count() == 0
    
    def test_request_parameters(self):
        """Test request parameter handling."""
        config = LLMProviderConfig(
            provider_type=ProviderType.MOCK,
            model="custom-model",
            temperature=0.5,
            max_tokens=100,
        )
        provider = MockProvider(config)
        
        request = provider.create_request(
            messages=[provider.create_user_message("test")],
        )
        
        assert request.model == "custom-model"
        assert request.temperature == 0.5
        assert request.max_tokens == 100
    
    def test_response_format(self):
        """Test structured output request."""
        config = LLMProviderConfig(provider_type=ProviderType.MOCK)
        provider = MockProvider(config)
        
        request = provider.create_request(
            messages=[provider.create_user_message("test")],
            response_format={"type": "json_object"},
        )
        
        assert request.response_format == {"type": "json_object"}
        
        response = provider.chat_completion(request)
        assert response.content is not None


class TestLLMMessage:
    """Test suite for LLMMessage."""
    
    def test_message_creation(self):
        """Test message creation."""
        msg = LLMMessage(role="user", content="Hello")
        
        assert msg.role == "user"
        assert msg.content == "Hello"
        assert msg.tool_call_id is None
        assert msg.tool_calls is None
    
    def test_message_serialization(self):
        """Test message to dict conversion."""
        msg = LLMMessage(role="user", content="Hello")
        msg_dict = msg.to_dict()
        
        assert msg_dict["role"] == "user"
        assert msg_dict["content"] == "Hello"
    
    def test_message_deserialization(self):
        """Test message from dict conversion."""
        msg_dict = {"role": "user", "content": "Hello"}
        msg = LLMMessage.from_dict(msg_dict)
        
        assert msg.role == "user"
        assert msg.content == "Hello"
    
    def test_message_with_tool_calls(self):
        """Test message with tool calls."""
        tool_call = LLMToolCall(
            id="call_123",
            function={"name": "search", "arguments": '{"query": "test"}'},
        )
        msg = LLMMessage(role="assistant", content="", tool_calls=[tool_call])
        
        assert msg.tool_calls is not None
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].id == "call_123"


class TestLLMToolCall:
    """Test suite for LLMToolCall."""
    
    def test_tool_call_creation(self):
        """Test tool call creation."""
        tool_call = LLMToolCall(
            id="call_123",
            function={"name": "search", "arguments": '{"query": "test"}'},
        )
        
        assert tool_call.id == "call_123"
        assert tool_call.function is not None
        assert tool_call.function["name"] == "search"
    
    def test_tool_call_serialization(self):
        """Test tool call to dict conversion."""
        tool_call = LLMToolCall(
            id="call_123",
            function={"name": "search", "arguments": '{"query": "test"}'},
        )
        tool_dict = tool_call.to_dict()
        
        assert tool_dict["id"] == "call_123"
        assert tool_dict["function"]["name"] == "search"


class TestLLMError:
    """Test suite for LLMError."""
    
    def test_error_creation(self):
        """Test error creation."""
        error = LLMError(
            message="Test error",
            error_type=LLMErrorType.RATE_LIMIT,
            provider="test-provider",
        )
        
        assert str(error) == "Test error"
        assert error.error_type == LLMErrorType.RATE_LIMIT
        assert error.provider == "test-provider"
    
    def test_error_to_dict(self):
        """Test error to dict conversion."""
        error = LLMError(
            message="Test error",
            error_type=LLMErrorType.RATE_LIMIT,
            provider="test-provider",
        )
        error_dict = error.to_dict()
        
        assert error_dict["error_type"] == "rate_limit"
        assert error_dict["provider"] == "test-provider"
        assert error_dict["message"] == "Test error"


class TestLLMResponse:
    """Test suite for LLMResponse."""
    
    def test_response_creation(self):
        """Test response creation."""
        response = LLMResponse(
            content="Hello",
            model="gpt-4",
            finish_reason="stop",
        )
        
        assert response.content == "Hello"
        assert response.model == "gpt-4"
        assert response.finish_reason == "stop"
    
    def test_response_serialization(self):
        """Test response to dict conversion."""
        response = LLMResponse(
            content="Hello",
            model="gpt-4",
            finish_reason="stop",
            usage={"total_tokens": 10},
        )
        response_dict = response.to_dict()
        
        assert response_dict["content"] == "Hello"
        assert response_dict["model"] == "gpt-4"
        assert response_dict["usage"]["total_tokens"] == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
