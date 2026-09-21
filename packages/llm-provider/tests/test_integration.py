"""Integration tests for LLM Provider with real API calls.

These tests require real API credentials and are optional.
Run with: OPENAI_API_KEY=sk-... pytest packages/llm-provider/tests/test_integration.py
"""

import os
import pytest

# Skip integration tests if no API key is provided
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="Requires OPENAI_API_KEY environment variable"
)

from llm_provider import (
    OpenAIProvider,
    LLMProviderConfig,
    ProviderType,
    LLMError,
    LLMErrorType,
)


class TestOpenAIProviderIntegration:
    """Integration tests for OpenAI provider with real API."""
    
    @pytest.fixture
    def provider(self):
        """Create OpenAI provider with real credentials."""
        config = LLMProviderConfig(
            provider_type=ProviderType.OPENAI,
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            timeout=30.0,
            max_retries=2,
        )
        return OpenAIProvider(config)
    
    def test_basic_chat_completion(self, provider):
        """Test basic chat completion with real API."""
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("Say 'Hello, World!' in exactly those words."),
            ],
            max_tokens=20,
        )
        
        response = provider.chat_completion(request)
        
        assert response.content is not None
        assert "Hello, World!" in response.content
        assert response.model is not None
        assert response.finish_reason == "stop"
        assert response.provider == "openai"
        assert response.latency_ms > 0
        assert response.usage.get("total_tokens", 0) > 0
    
    def test_structured_output(self, provider):
        """Test structured output (JSON mode)."""
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a data analyst."),
                provider.create_user_message("Provide a JSON object with 'status' and 'message' fields."),
            ],
            response_format={"type": "json_object"},
            max_tokens=100,
        )
        
        response = provider.chat_completion(request)
        
        assert response.content is not None
        # Verify it's valid JSON
        import json
        try:
            data = json.loads(response.content)
            assert "status" in data or "message" in data
        except json.JSONDecodeError:
            pytest.fail("Response is not valid JSON")
    
    def test_temperature_parameter(self, provider):
        """Test temperature parameter affects response."""
        # Low temperature for deterministic response
        request_low = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("Choose a random number between 1 and 10."),
            ],
            temperature=0.0,
            max_tokens=10,
        )
        
        response_low = provider.chat_completion(request)
        
        # High temperature for more varied response
        request_high = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("Choose a random number between 1 and 10."),
            ],
            temperature=1.0,
            max_tokens=10,
        )
        
        response_high = provider.chat_completion(request)
        
        assert response_low.content is not None
        assert response_high.content is not None
        # Both should return numbers
        assert any(char.isdigit() for char in response_low.content)
        assert any(char.isdigit() for char in response_high.content)
    
    def test_max_tokens_parameter(self, provider):
        """Test max_tokens parameter limits response length."""
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("Write a very long paragraph about AI."),
            ],
            max_tokens=50,
        )
        
        response = provider.chat_completion(request)
        
        assert response.content is not None
        # Check that response is reasonably short
        assert len(response.content.split()) <= 60  # Allow some margin
    
    def test_tool_calling_basic(self, provider):
        """Test basic tool calling capability."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get current weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "City name",
                            },
                        },
                        "required": ["location"],
                    },
                },
            }
        ]
        
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("What's the weather in San Francisco?"),
            ],
            tools=tools,
            tool_choice="auto",
        )
        
        response = provider.chat_completion(request)
        
        assert response.content is not None
        # Tool calls might or might not be present depending on model behavior
        if response.tool_calls:
            assert len(response.tool_calls) > 0
            assert response.tool_calls[0].function is not None
            assert response.tool_calls[0].function["name"] == "get_weather"
    
    def test_error_handling_invalid_key(self):
        """Test error handling with invalid API key."""
        config = LLMProviderConfig(
            provider_type=ProviderType.OPENAI,
            api_key="invalid-key-12345",
            model="gpt-4o-mini",
            timeout=10.0,
            max_retries=1,
        )
        provider = OpenAIProvider(config)
        
        request = provider.create_request(
            messages=[provider.create_user_message("test")],
        )
        
        with pytest.raises(LLMError) as exc_info:
            provider.chat_completion(request)
        
        assert exc_info.value.error_type in (LLMErrorType.AUTHENTICATION, LLMErrorType.UNKNOWN)
    
    def test_health_check(self, provider):
        """Test health check with real API."""
        # Health check should succeed with valid credentials
        is_healthy = provider.health_check()
        assert is_healthy is True
    
    def test_multiple_messages(self, provider):
        """Test conversation with multiple messages."""
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("My name is Alice."),
                provider.create_assistant_message("Hello Alice! How can I help you today?"),
                provider.create_user_message("What's my name?"),
            ],
            max_tokens=20,
        )
        
        response = provider.chat_completion(request)
        
        assert response.content is not None
        assert "Alice" in response.content
    
    def test_observability_metadata(self, provider):
        """Test that response includes comprehensive metadata."""
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("Hello!"),
            ],
        )
        
        response = provider.chat_completion(request)
        
        # Check all metadata fields
        assert response.content is not None
        assert response.model is not None
        assert response.finish_reason is not None
        assert response.usage is not None
        assert response.usage.get("prompt_tokens", 0) > 0
        assert response.usage.get("completion_tokens", 0) > 0
        assert response.usage.get("total_tokens", 0) > 0
        assert response.latency_ms > 0
        assert response.timestamp is not None
        assert response.provider == "openai"
    
    def test_custom_base_url(self):
        """Test provider with custom base URL (e.g., DeepSeek)."""
        base_url = os.getenv("OPENAI_BASE_URL")
        if not base_url:
            pytest.skip("Requires OPENAI_BASE_URL environment variable")
        
        config = LLMProviderConfig(
            provider_type=ProviderType.OPENAI,
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=base_url,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            timeout=30.0,
        )
        provider = OpenAIProvider(config)
        
        request = provider.create_request(
            messages=[
                provider.create_system_message("You are a helpful assistant."),
                provider.create_user_message("Say 'Custom base URL test'"),
            ],
            max_tokens=20,
        )
        
        response = provider.chat_completion(request)
        
        assert response.content is not None
        assert "Custom base URL test" in response.content


class TestDeepSeekIntegration:
    """Integration tests specifically for DeepSeek provider."""
    
    @pytest.fixture
    def deepseek_provider(self):
        """Create DeepSeek provider if configured."""
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            pytest.skip("Requires DEEPSEEK_API_KEY or OPENAI_API_KEY")
        
        config = LLMProviderConfig(
            provider_type=ProviderType.OPENAI,
            api_key=api_key,
            base_url=base_url,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            timeout=30.0,
        )
        return OpenAIProvider(config)
    
    def test_deepseek_basic_completion(self, deepseek_provider):
        """Test basic completion with DeepSeek."""
        request = deepseek_provider.create_request(
            messages=[
                deepseek_provider.create_system_message("You are a helpful assistant."),
                deepseek_provider.create_user_message("Say 'DeepSeek test'"),
            ],
            max_tokens=20,
        )
        
        response = deepseek_provider.chat_completion(request)
        
        assert response.content is not None
        assert "DeepSeek test" in response.content
        assert response.provider == "openai"  # Provider type is still openai-compatible


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
