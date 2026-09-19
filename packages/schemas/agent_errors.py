"""Standardized Error Model for A2A Agent Responses.

This module provides unified error definitions and helpers for consistent
error handling across AOP reference agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .agent_manifest import ErrorCode


@dataclass
class AgentError:
    """Standardized error response structure."""

    code: str  # ErrorCode enum value
    message: str  # Human-readable error message
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    request_id: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @classmethod
    def invalid_request(cls, message: str, **details: Any) -> AgentError:
        return cls(
            code=ErrorCode.INVALID_REQUEST.value,
            message=message,
            details=details,
        )

    @classmethod
    def unsupported_skill(cls, skill_id: str, available_skills: list[str]) -> AgentError:
        return cls(
            code=ErrorCode.UNSUPPORTED_SKILL.value,
            message=f"Unsupported skill: {skill_id}",
            details={
                "requested_skill": skill_id,
                "available_skills": available_skills,
            },
        )

    @classmethod
    def auth_failed(cls, reason: str = "Authentication failed") -> AgentError:
        return cls(
            code=ErrorCode.AUTH_FAILED.value,
            message=reason,
            details={"auth_reason": reason},
        )

    @classmethod
    def task_not_found(cls, task_id: str) -> AgentError:
        return cls(
            code=ErrorCode.TASK_NOT_FOUND.value,
            message=f"Task not found: {task_id}",
            details={"task_id": task_id},
        )

    @classmethod
    def execution_failed(cls, reason: str, skill_id: str | None = None) -> AgentError:
        details = {"reason": reason}
        if skill_id:
            details["skill_id"] = skill_id
        return cls(
            code=ErrorCode.EXECUTION_FAILED.value,
            message=f"Execution failed: {reason}",
            details=details,
        )

    @classmethod
    def timeout(cls, operation: str, timeout_seconds: int) -> AgentError:
        return cls(
            code=ErrorCode.TIMEOUT.value,
            message=f"Operation timeout: {operation}",
            details={
                "operation": operation,
                "timeout_seconds": timeout_seconds,
            },
        )

    @classmethod
    def resource_exhausted(cls, resource_type: str, limit: int | None = None) -> AgentError:
        details = {"resource_type": resource_type}
        if limit is not None:
            details["limit"] = limit
        return cls(
            code=ErrorCode.RESOURCE_EXHAUSTED.value,
            message=f"Resource exhausted: {resource_type}",
            details=details,
        )

    @classmethod
    def internal_error(cls, reason: str, **details: Any) -> AgentError:
        return cls(
            code=ErrorCode.INTERNAL_ERROR.value,
            message=f"Internal error: {reason}",
            details={"reason": reason, **details},
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format for JSON-RPC error response."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "requestId": self.request_id,
        }

    def to_jsonrpc_error(self, jsonrpc_id: str | None = None) -> dict[str, Any]:
        """Convert to JSON-RPC 2.0 error format."""
        error_data = self.to_dict()
        return {
            "jsonrpc": "2.0",
            "id": jsonrpc_id,
            "error": {
                "code": self._map_to_jsonrpc_code(self.code),
                "message": self.message,
                "data": error_data,
            },
        }

    def _map_to_jsonrpc_code(self, code: str) -> int:
        """Map standardized error codes to JSON-RPC error codes."""
        # Keep JSON-RPC compatibility for common errors
        code_mapping = {
            ErrorCode.INVALID_REQUEST.value: -32602,
            ErrorCode.TASK_NOT_FOUND.value: -32001,
            ErrorCode.UNSUPPORTED_SKILL.value: -32601,
            ErrorCode.INTERNAL_ERROR.value: -32603,
        }
        return code_mapping.get(code, -32000)  # Server error for unknown codes


@dataclass
class ErrorResponse:
    """Standardized error response wrapper for A2A endpoints."""

    error: AgentError

    def to_jsonrpc_response(self, jsonrpc_id: str | None = None) -> dict[str, Any]:
        """Convert to JSON-RPC 2.0 response format."""
        return self.error.to_jsonrpc_error(jsonrpc_id)

    def to_http_response(self, status_code: int = 400) -> dict[str, Any]:
        """Convert to HTTP response format."""
        return {
            "error": self.error.to_dict(),
            "status_code": status_code,
        }


def handle_agent_error(exc: Exception, context: str = "") -> AgentError:
    """Convert exceptions to standardized AgentError."""
    import traceback

    error_context = context if context else "operation"
    error_message = f"{error_context} failed: {str(exc)}"

    # Check for known exception types
    if isinstance(exc, ValueError):
        return AgentError.invalid_request(error_message)
    if isinstance(exc, KeyError):
        return AgentError.invalid_request(f"Missing required field: {exc}")
    if isinstance(exc, TimeoutError):
        return AgentError.timeout(error_context, timeout_seconds=60)

    # Default to internal error
    traceback_str = traceback.format_exc()
    return AgentError.internal_error(
        error_message,
        exception_type=type(exc).__name__,
        traceback=traceback_str[:1000],  # Limit traceback length
    )


__all__ = [
    "AgentError",
    "ErrorResponse",
    "handle_agent_error",
]
