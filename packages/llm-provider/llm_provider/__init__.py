"""Unified LLM Provider for AOP Agents.

This package provides a standardized interface for LLM interactions across
all AOP agents, supporting multiple providers (OpenAI-compatible, etc.) with
consistent error handling, observability, and tool calling capabilities.
"""

from .provider import (
    LLMProvider,
    LLMProviderConfig,
    LLMRequest,
    LLMResponse,
    LLMMessage,
    LLMToolCall,
    LLMToolResult,
    LLMError,
    LLMErrorType,
    ProviderType,
)
from .openai_provider import OpenAIProvider
from .mock_provider import MockProvider

__all__ = [
    "LLMProvider",
    "LLMProviderConfig",
    "LLMRequest",
    "LLMResponse",
    "LLMMessage",
    "LLMToolCall",
    "LLMToolResult",
    "LLMError",
    "LLMErrorType",
    "ProviderType",
    "OpenAIProvider",
    "MockProvider",
]
