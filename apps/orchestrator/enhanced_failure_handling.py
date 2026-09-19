"""Enhanced failure handling with idempotency integration (P36.3).

This module provides improved timeout handling, circuit breaker integration,
and enhanced error classification for distributed task execution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any
from datetime import datetime, timezone


class ErrorCategory(Enum):
    """Enhanced error classification for better failure handling."""
    NETWORK = "network"
    TIMEOUT = "timeout"
    AGENT_UNAVAILABLE = "agent_unavailable"
    AGENT_ERROR = "agent_error"
    VALIDATION = "validation"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    UNKNOWN = "unknown"


class RecoveryStrategy(Enum):
    """Recovery strategies for different error types."""
    RETRY_WITH_SAME_AGENT = "retry_same"
    RETRY_WITH_DIFFERENT_AGENT = "retry_different"
    FAIL_FAST = "fail_fast"
    CIRCUIT_BREAK = "circuit_break"
    MANUAL_INTERVENTION = "manual"


@dataclass
class FailureContext:
    """Context for failure handling decisions."""
    task_id: str
    node_key: str
    skill: str
    attempt: int
    error_message: str
    error_category: ErrorCategory
    agent_id: str | None = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


class EnhancedFailureHandler:
    """Enhanced failure handler with idempotency integration."""
    
    def __init__(self):
        self.failure_history: dict[str, list[FailureContext]] = {}
        self.circuit_breaker_states: dict[str, bool] = {}  # agent_id -> is_open
        
    def classify_error(self, error_message: str) -> ErrorCategory:
        """Classify error based on message content."""
        error_lower = error_message.lower()
        
        if "timeout" in error_lower or "timed out" in error_lower:
            return ErrorCategory.TIMEOUT
        elif "connection" in error_lower or "network" in error_lower:
            return ErrorCategory.NETWORK
        elif "agent" in error_lower and ("not found" in error_lower or "unavailable" in error_lower):
            return ErrorCategory.AGENT_UNAVAILABLE
        elif "agent" in error_lower:
            return ErrorCategory.AGENT_ERROR
        elif "validation" in error_lower or "invalid" in error_lower:
            return ErrorCategory.VALIDATION
        elif "resource" in error_lower or "exhausted" in error_lower:
            return ErrorCategory.RESOURCE_EXHAUSTED
        else:
            return ErrorCategory.UNKNOWN
    
    def determine_recovery_strategy(
        self,
        context: FailureContext,
        max_attempts: int = 3,
    ) -> RecoveryStrategy:
        """Determine recovery strategy based on failure context."""
        
        # Check if circuit breaker is open for this agent
        if context.agent_id and self.is_circuit_breaker_open(context.agent_id):
            return RecoveryStrategy.RETRY_WITH_DIFFERENT_AGENT
        
        # Check if max attempts exceeded
        if context.attempt >= max_attempts:
            return RecoveryStrategy.FAIL_FAST
        
        # Error-specific strategies
        if context.error_category == ErrorCategory.TIMEOUT:
            # Timeouts can be retried with same agent (idempotency handles duplicates)
            return RecoveryStrategy.RETRY_WITH_SAME_AGENT
        elif context.error_category == ErrorCategory.NETWORK:
            # Network errors can be retried with same agent
            return RecoveryStrategy.RETRY_WITH_SAME_AGENT
        elif context.error_category == ErrorCategory.AGENT_UNAVAILABLE:
            # Agent unavailable - try different agent
            return RecoveryStrategy.RETRY_WITH_DIFFERENT_AGENT
        elif context.error_category == ErrorCategory.AGENT_ERROR:
            # Agent error - try different agent to avoid repeating same error
            return RecoveryStrategy.RETRY_WITH_DIFFERENT_AGENT
        elif context.error_category == ErrorCategory.VALIDATION:
            # Validation errors are permanent - fail fast
            return RecoveryStrategy.FAIL_FAST
        elif context.error_category == ErrorCategory.RESOURCE_EXHAUSTED:
            # Resource exhaustion - circuit break
            return RecoveryStrategy.CIRCUIT_BREAK
        else:
            # Unknown errors - retry with same agent
            return RecoveryStrategy.RETRY_WITH_SAME_AGENT
    
    def record_failure(self, context: FailureContext) -> None:
        """Record failure for pattern analysis."""
        key = f"{context.task_id}:{context.node_key}"
        if key not in self.failure_history:
            self.failure_history[key] = []
        self.failure_history[key].append(context)
        
        # Update circuit breaker state
        if context.agent_id:
            self.update_circuit_breaker(context.agent_id, context.error_category)
    
    def is_circuit_breaker_open(self, agent_id: str) -> bool:
        """Check if circuit breaker is open for an agent."""
        return self.circuit_breaker_states.get(agent_id, False)
    
    def update_circuit_breaker(
        self,
        agent_id: str,
        error_category: ErrorCategory,
    ) -> None:
        """Update circuit breaker state based on error category."""
        if error_category in [ErrorCategory.RESOURCE_EXHAUSTED, ErrorCategory.AGENT_ERROR]:
            # Open circuit breaker for these error types
            self.circuit_breaker_states[agent_id] = True
        elif error_category == ErrorCategory.TIMEOUT:
            # Only open circuit breaker after multiple timeouts
            failures = [f for f in self.failure_history.values() 
                       for c in f if c.agent_id == agent_id and c.error_category == ErrorCategory.TIMEOUT]
            if len(failures) >= 3:
                self.circuit_breaker_states[agent_id] = True
    
    def reset_circuit_breaker(self, agent_id: str) -> None:
        """Reset circuit breaker for an agent."""
        self.circuit_breaker_states[agent_id] = False
    
    def get_failure_pattern(self, task_id: str, node_key: str) -> dict[str, Any]:
        """Analyze failure pattern for a task node."""
        key = f"{task_id}:{node_key}"
        failures = self.failure_history.get(key, [])
        
        if not failures:
            return {"total_failures": 0}
        
        error_categories = {}
        for failure in failures:
            cat = failure.error_category.value
            error_categories[cat] = error_categories.get(cat, 0) + 1
        
        return {
            "total_failures": len(failures),
            "error_categories": error_categories,
            "last_error": failures[-1].error_message,
            "last_error_category": failures[-1].error_category.value,
        }
    
    def should_fail_fast(self, context: FailureContext) -> bool:
        """Determine if failure should result in immediate task failure."""
        strategy = self.determine_recovery_strategy(context)
        return strategy == RecoveryStrategy.FAIL_FAST
    
    def get_retry_delay(self, context: FailureContext) -> float:
        """Calculate retry delay based on failure context."""
        # Exponential backoff based on attempt number
        base_delay = 1.0
        max_delay = 30.0
        delay = min(base_delay * (2 ** (context.attempt - 1)), max_delay)
        
        # Add jitter
        jitter = delay * 0.1
        return delay + (time.time() % jitter)


# Singleton instance
_failure_handler: EnhancedFailureHandler | None = None


def get_failure_handler() -> EnhancedFailureHandler:
    """Get or create the singleton failure handler."""
    global _failure_handler
    if _failure_handler is None:
        _failure_handler = EnhancedFailureHandler()
    return _failure_handler
