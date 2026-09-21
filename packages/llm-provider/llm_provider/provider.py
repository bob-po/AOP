"""Core LLM Provider interface and data structures."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ProviderType(Enum):
    """Supported LLM provider types."""
    OPENAI = "openai"
    MOCK = "mock"
    CUSTOM = "custom"


class LLMErrorType(Enum):
    """Classification of LLM errors for handling and observability."""
    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    VALIDATION = "validation"
    PROVIDER = "provider"
    UNKNOWN = "unknown"


class LLMError(Exception):
    """Standardized LLM error with classification."""
    
    def __init__(
        self,
        message: str,
        error_type: LLMErrorType = LLMErrorType.UNKNOWN,
        provider: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.provider = provider
        self.details = details or {}
        self.original_error = original_error
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": self.error_type.value,
            "provider": self.provider,
            "message": str(self),
            "details": self.details,
        }


@dataclass
class LLMMessage:
    """Standardized message format for LLM interactions."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[LLMToolCall]] = None
    
    def to_dict(self) -> dict[str, Any]:
        result = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        if self.tool_calls:
            result["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        return result
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMMessage:
        return cls(
            role=data["role"],
            content=data["content"],
            tool_call_id=data.get("tool_call_id"),
            tool_calls=[LLMToolCall.from_dict(tc) for tc in data.get("tool_calls", [])] if data.get("tool_calls") else None,
        )


@dataclass
class LLMToolCall:
    """Represents a tool call requested by the LLM."""
    id: str
    type: str = "function"
    function: Optional[dict[str, Any]] = None
    
    def to_dict(self) -> dict[str, Any]:
        result = {"id": self.id, "type": self.type}
        if self.function:
            result["function"] = self.function
        return result
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LLMToolCall:
        return cls(
            id=data["id"],
            type=data.get("type", "function"),
            function=data.get("function"),
        )


@dataclass
class LLMToolResult:
    """Result from executing a tool call."""
    tool_call_id: str
    content: str
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


@dataclass
class LLMRequest:
    """Standardized LLM request structure."""
    messages: list[LLMMessage]
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    tools: Optional[list[dict[str, Any]]] = None
    tool_choice: Optional[str] = None  # "auto", "none", "required", or specific tool
    response_format: Optional[dict[str, str]] = None  # For structured output
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        result = {
            "messages": [msg.to_dict() for msg in self.messages],
            "model": self.model,
            "temperature": self.temperature,
        }
        if self.max_tokens:
            result["max_tokens"] = self.max_tokens
        if self.tools:
            result["tools"] = self.tools
        if self.tool_choice:
            result["tool_choice"] = self.tool_choice
        if self.response_format:
            result["response_format"] = self.response_format
        return result


@dataclass
class LLMResponse:
    """Standardized LLM response with observability data."""
    content: str
    model: str
    finish_reason: str
    tool_calls: Optional[list[LLMToolCall]] = None
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: Optional[str] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "finish_reason": self.finish_reason,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls] if self.tool_calls else None,
            "usage": self.usage,
            "latency_ms": self.latency_ms,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "provider": self.provider,
        }


@dataclass
class LLMProviderConfig:
    """Configuration for LLM providers."""
    provider_type: ProviderType = ProviderType.OPENAI
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: str = "gpt-4o-mini"
    timeout: float = 60.0
    max_retries: int = 3
    retry_delay: float = 1.0
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_type": self.provider_type.value,
            "api_key": "***" if self.api_key else None,  # Never log actual keys
            "base_url": self.base_url,
            "model": self.model,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self, config: LLMProviderConfig):
        self.config = config
        self._provider_name = config.provider_type.value
    
    @property
    def provider_name(self) -> str:
        return self._provider_name
    
    @abstractmethod
    def chat_completion(self, request: LLMRequest) -> LLMResponse:
        """Execute a chat completion request."""
        pass
    
    @abstractmethod
    def health_check(self) -> bool:
        """Check if the provider is healthy and accessible."""
        pass
    
    def create_system_message(self, content: str) -> LLMMessage:
        """Helper to create a system message."""
        return LLMMessage(role="system", content=content)
    
    def create_user_message(self, content: str) -> LLMMessage:
        """Helper to create a user message."""
        return LLMMessage(role="user", content=content)
    
    def create_assistant_message(self, content: str, tool_calls: Optional[list[LLMToolCall]] = None) -> LLMMessage:
        """Helper to create an assistant message."""
        return LLMMessage(role="assistant", content=content, tool_calls=tool_calls)
    
    def create_tool_message(self, tool_call_id: str, content: str) -> LLMMessage:
        """Helper to create a tool result message."""
        return LLMMessage(role="tool", content=content, tool_call_id=tool_call_id)
    
    def create_request(
        self,
        messages: list[LLMMessage],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, str]] = None,
    ) -> LLMRequest:
        """Helper to create a request with defaults from config."""
        return LLMRequest(
            messages=messages,
            model=model or self.config.model,
            temperature=temperature if temperature is not None else self.config.temperature,
            max_tokens=max_tokens or self.config.max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            response_format=response_format,
        )


__all__ = [
    "ProviderType",
    "LLMErrorType",
    "LLMError",
    "LLMMessage",
    "LLMToolCall",
    "LLMToolResult",
    "LLMRequest",
    "LLMResponse",
    "LLMProviderConfig",
    "LLMProvider",
]
