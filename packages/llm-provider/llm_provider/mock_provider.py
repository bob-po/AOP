"""Mock LLM provider for testing and development."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .provider import (
    LLMProvider,
    LLMProviderConfig,
    LLMRequest,
    LLMResponse,
    LLMMessage,
    LLMToolCall,
    LLMError,
    LLMErrorType,
    ProviderType,
)

logger = logging.getLogger(__name__)


class MockProvider(LLMProvider):
    """Mock LLM provider for testing without real API calls."""
    
    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self._call_count = 0
        self._responses: dict[str, str] = {}
        self._should_fail = False
        self._failure_type = LLMErrorType.UNKNOWN
        self._latency_ms = 10  # Simulate minimal latency
    
    def set_response(self, key: str, response: str) -> None:
        """Set a canned response for a specific request key."""
        self._responses[key] = response
    
    def set_failure(self, should_fail: bool, failure_type: LLMErrorType = LLMErrorType.UNKNOWN) -> None:
        """Configure the mock to fail on next request."""
        self._should_fail = should_fail
        self._failure_type = failure_type
    
    def set_latency(self, latency_ms: int) -> None:
        """Set simulated latency in milliseconds."""
        self._latency_ms = latency_ms
    
    def reset(self) -> None:
        """Reset mock state."""
        self._call_count = 0
        self._responses.clear()
        self._should_fail = False
        self._failure_type = LLMErrorType.UNKNOWN
    
    def get_call_count(self) -> int:
        """Get the number of calls made to this provider."""
        return self._call_count
    
    def _generate_response(self, request: LLMRequest) -> str:
        """Generate a mock response based on the request."""
        # Check for canned response
        request_key = self._request_to_key(request)
        if request_key in self._responses:
            return self._responses[request_key]
        
        # Generate default response based on last user message
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if user_messages:
            last_user_msg = user_messages[-1].content
            return f"Mock response to: {last_user_msg[:100]}..."
        
        return "Mock response from MockProvider"
    
    def _request_to_key(self, request: LLMRequest) -> str:
        """Create a simple key for caching responses."""
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if user_messages:
            return user_messages[-1].content[:50]
        return "default"
    
    def chat_completion(self, request: LLMRequest) -> LLMResponse:
        """Execute a mock chat completion."""
        self._call_count += 1
        
        start_time = time.time()
        
        # Simulate latency
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000.0)
        
        # Check if configured to fail
        if self._should_fail:
            raise LLMError(
                f"Mock provider failure (type: {self._failure_type.value})",
                error_type=self._failure_type,
                provider=self.provider_name,
            )
        
        # Generate response
        content = self._generate_response(request)
        
        # Simulate tool calls if tools are requested
        tool_calls = None
        if request.tools and request.tool_choice in ("auto", "required"):
            # Generate a mock tool call
            tool_calls = [
                LLMToolCall(
                    id=f"call_{self._call_count}",
                    function={
                        "name": request.tools[0]["function"]["name"] if request.tools else "mock_tool",
                        "arguments": '{"param": "value"}',
                    },
                )
            ]
        
        latency_ms = int((time.time() - start_time) * 1000)
        
        return LLMResponse(
            content=content,
            model=request.model,
            finish_reason="stop",
            tool_calls=tool_calls,
            usage={
                "prompt_tokens": sum(len(msg.content.split()) for msg in request.messages),
                "completion_tokens": len(content.split()),
                "total_tokens": sum(len(msg.content.split()) for msg in request.messages) + len(content.split()),
            },
            latency_ms=latency_ms,
            metadata=request.metadata,
            provider=self.provider_name,
        )
    
    def health_check(self) -> bool:
        """Mock health check always returns True."""
        return True


__all__ = ["MockProvider"]
