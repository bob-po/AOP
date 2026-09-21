"""OpenAI-compatible LLM provider implementation."""

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


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible LLM provider (supports OpenAI, DeepSeek, etc.)."""
    
    def __init__(self, config: LLMProviderConfig):
        super().__init__(config)
        self._client = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize the OpenAI client with configuration."""
        try:
            from openai import OpenAI
            
            client_kwargs: dict[str, Any] = {
                "api_key": self.config.api_key or "",
                "timeout": self.config.timeout,
            }
            
            if self.config.base_url:
                client_kwargs["base_url"] = self.config.base_url
            
            self._client = OpenAI(**client_kwargs)
            logger.info(f"OpenAI provider initialized: model={self.config.model}, base_url={self.config.base_url}")
            
        except ImportError as e:
            raise LLMError(
                "OpenAI package not installed. Install with: pip install openai",
                error_type=LLMErrorType.PROVIDER,
                provider=self.provider_name,
                original_error=e,
            )
        except Exception as e:
            raise LLMError(
                f"Failed to initialize OpenAI client: {str(e)}",
                error_type=LLMErrorType.PROVIDER,
                provider=self.provider_name,
                original_error=e,
            )
    
    def _classify_error(self, error: Exception) -> LLMErrorType:
        """Classify OpenAI errors into standard types."""
        error_msg = str(error).lower()
        
        if "authentication" in error_msg or "api key" in error_msg or "unauthorized" in error_msg:
            return LLMErrorType.AUTHENTICATION
        elif "rate limit" in error_msg or "429" in error_msg:
            return LLMErrorType.RATE_LIMIT
        elif "timeout" in error_msg or "timed out" in error_msg:
            return LLMErrorType.TIMEOUT
        elif "network" in error_msg or "connection" in error_msg or "dns" in error_msg:
            return LLMErrorType.NETWORK
        elif "validation" in error_msg or "invalid" in error_msg or "400" in error_msg:
            return LLMErrorType.VALIDATION
        elif "500" in error_msg or "502" in error_msg or "503" in error_msg:
            return LLMErrorType.PROVIDER
        else:
            return LLMErrorType.UNKNOWN
    
    def _retry_with_backoff(self, func, *args, **kwargs) -> Any:
        """Execute function with exponential backoff retry."""
        last_error = None
        
        for attempt in range(self.config.max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_type = self._classify_error(e)
                
                # Don't retry authentication or validation errors
                if error_type in (LLMErrorType.AUTHENTICATION, LLMErrorType.VALIDATION):
                    raise
                
                # Don't retry on last attempt
                if attempt == self.config.max_retries - 1:
                    raise
                
                # Calculate delay with exponential backoff
                delay = self.config.retry_delay * (2 ** attempt)
                logger.warning(
                    f"OpenAI request failed (attempt {attempt + 1}/{self.config.max_retries}), "
                    f"retrying in {delay}s: {str(e)}"
                )
                time.sleep(delay)
        
        raise last_error
    
    def chat_completion(self, request: LLMRequest) -> LLMResponse:
        """Execute a chat completion request with retry logic."""
        if not self._client:
            raise LLMError(
                "OpenAI client not initialized",
                error_type=LLMErrorType.PROVIDER,
                provider=self.provider_name,
            )
        
        start_time = time.time()
        
        def _make_request() -> LLMResponse:
            try:
                # Convert request to OpenAI format
                messages_dict = [msg.to_dict() for msg in request.messages]
                create_kwargs: dict[str, Any] = {
                    "model": request.model,
                    "messages": messages_dict,
                    "temperature": request.temperature,
                }
                
                if request.max_tokens:
                    create_kwargs["max_tokens"] = request.max_tokens
                if request.tools:
                    create_kwargs["tools"] = request.tools
                if request.tool_choice:
                    create_kwargs["tool_choice"] = request.tool_choice
                if request.response_format:
                    create_kwargs["response_format"] = request.response_format
                
                # Make the API call
                response = self._client.chat.completions.create(**create_kwargs)
                
                # Extract response data
                choice = response.choices[0]
                message = choice.message
                
                # Convert tool calls if present
                tool_calls = None
                if message.tool_calls:
                    tool_calls = [
                        LLMToolCall(
                            id=tc.id,
                            type=tc.type,
                            function={
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            } if tc.function else None,
                        )
                        for tc in message.tool_calls
                    ]
                
                # Build usage information
                usage = {}
                if response.usage:
                    usage = {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens,
                    }
                
                latency_ms = int((time.time() - start_time) * 1000)
                
                return LLMResponse(
                    content=message.content or "",
                    model=response.model,
                    finish_reason=choice.finish_reason or "unknown",
                    tool_calls=tool_calls,
                    usage=usage,
                    latency_ms=latency_ms,
                    metadata=request.metadata,
                    provider=self.provider_name,
                )
                
            except Exception as e:
                error_type = self._classify_error(e)
                raise LLMError(
                    f"OpenAI API error: {str(e)}",
                    error_type=error_type,
                    provider=self.provider_name,
                    details={"model": request.model},
                    original_error=e,
                )
        
        return self._retry_with_backoff(_make_request)
    
    def health_check(self) -> bool:
        """Check if the OpenAI provider is healthy."""
        if not self._client:
            return False
        
        try:
            # Simple health check: list models or make a minimal request
            # We'll try a minimal completion request
            test_request = self.create_request(
                messages=[self.create_user_message("test")],
                max_tokens=1,
            )
            self.chat_completion(test_request)
            return True
        except Exception as e:
            logger.warning(f"OpenAI health check failed: {str(e)}")
            return False


__all__ = ["OpenAIProvider"]
