"""Enhanced error handling and retry mechanisms."""

from __future__ import annotations

import time
import traceback
from enum import Enum
from typing import Any, Callable, Optional, TypeVar, Dict
from functools import wraps
import logging

T = TypeVar('T')

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Error categories for different handling strategies."""
    TRANSIENT = "transient"           # Temporary errors, should retry
    PERMANENT = "permanent"           # Permanent errors, don't retry
    RATE_LIMIT = "rate_limit"         # Rate limiting, backoff aggressively
    TIMEOUT = "timeout"               # Timeout errors, may retry with longer timeout
    VALIDATION = "validation"         # Input validation errors, don't retry
    NETWORK = "network"               # Network issues, should retry
    AGENT_UNAVAILABLE = "agent_unavailable"  # Agent not available, try other agent


class AOPError(Exception):
    """Base error class for AOP platform."""
    
    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.TRANSIENT,
        retryable: bool = True,
        context: Optional[Dict[str, Any]] = None,
        original_error: Optional[Exception] = None
    ):
        self.message = message
        self.category = category
        self.retryable = retryable
        self.context = context or {}
        self.original_error = original_error
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert error to dictionary for logging/serialization."""
        return {
            "error_type": self.__class__.__name__,
            "message": self.message,
            "category": self.category.value,
            "retryable": self.retryable,
            "context": self.context,
            "original_error": str(self.original_error) if self.original_error else None
        }


class AgentError(AOPError):
    """Agent-related errors."""
    pass


class DatabaseError(AOPError):
    """Database-related errors."""
    pass


class NetworkError(AOPError):
    """Network-related errors."""
    pass


class ValidationError(AOPError):
    """Validation errors."""
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(
            message, 
            category=ErrorCategory.VALIDATION, 
            retryable=False, 
            context=context
        )


class TimeoutError(AOPError):
    """Timeout errors."""
    def __init__(self, message: str, timeout: float, context: Optional[Dict[str, Any]] = None):
        context = context or {}
        context["timeout"] = timeout
        super().__init__(
            message, 
            category=ErrorCategory.TIMEOUT, 
            retryable=True, 
            context=context
        )


class RateLimitError(AOPError):
    """Rate limiting errors."""
    def __init__(self, message: str, retry_after: float, context: Optional[Dict[str, Any]] = None):
        context = context or {}
        context["retry_after"] = retry_after
        super().__init__(
            message, 
            category=ErrorCategory.RATE_LIMIT, 
            retryable=True, 
            context=context
        )


class CircuitBreakerOpenError(AOPError):
    """Circuit breaker is open."""
    def __init__(self, service: str, reset_time: float):
        super().__init__(
            f"Circuit breaker open for {service}, try again at {reset_time}",
            category=ErrorCategory.TRANSIENT,
            retryable=False,
            context={"service": service, "reset_time": reset_time}
        )


class RetryPolicy:
    """Configurable retry policy."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True,
        retryable_categories: Optional[set[ErrorCategory]] = None
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
        self.retryable_categories = retryable_categories or {
            ErrorCategory.TRANSIENT,
            ErrorCategory.NETWORK,
            ErrorCategory.TIMEOUT,
            ErrorCategory.AGENT_UNAVAILABLE
        }
    
    def should_retry(self, error: Exception, attempt: int) -> bool:
        """Determine if error should be retried."""
        if attempt >= self.max_attempts:
            return False
        
        if isinstance(error, AOPError):
            return error.retryable and error.category in self.retryable_categories
        
        # For non-AOP errors, be conservative
        return attempt < self.max_attempts
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for next retry attempt."""
        delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            delay = delay * (0.5 + random.random() * 0.5)  # ±50% jitter
        
        return delay


class CircuitBreaker:
    """Circuit breaker pattern implementation."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold
        
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.state = "closed"  # closed, open, half_open
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection."""
        if self.state == "open":
            if self._should_attempt_reset():
                self.state = "half_open"
                logger.info("Circuit breaker transitioning to half-open")
            else:
                raise CircuitBreakerOpenError(
                    "circuit_breaker",
                    time.time() + self.recovery_timeout - (self.last_failure_time or 0)
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """Check if circuit breaker should attempt to reset."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.recovery_timeout
    
    def _on_success(self) -> None:
        """Handle successful execution."""
        if self.state == "half_open":
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = "closed"
                self.failure_count = 0
                self.success_count = 0
                logger.info("Circuit breaker reset to closed")
        else:
            self.failure_count = 0
    
    def _on_failure(self) -> None:
        """Handle failed execution."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        self.success_count = 0
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
    
    def get_state(self) -> Dict[str, Any]:
        """Get current circuit breaker state."""
        return {
            "state": self.state,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure_time": self.last_failure_time
        }


def with_retry(
    policy: Optional[RetryPolicy] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """Decorator for automatic retry with configurable policy."""
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            retry_policy = policy or RetryPolicy()
            last_error = None
            
            for attempt in range(1, retry_policy.max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    
                    if not retry_policy.should_retry(e, attempt):
                        logger.error(
                            f"Function {func.__name__} failed after {attempt} attempts: {e}"
                        )
                        raise
                    
                    delay = retry_policy.get_delay(attempt)
                    logger.warning(
                        f"Function {func.__name__} failed (attempt {attempt}/{retry_policy.max_attempts}), "
                        f"retrying in {delay:.2f}s: {e}"
                    )
                    
                    if on_retry:
                        on_retry(e, attempt)
                    
                    time.sleep(delay)
            
            # This should never be reached, but just in case
            if last_error:
                raise last_error
            raise RuntimeError("Unexpected error in retry logic")
        
        return wrapper
    return decorator


def classify_error(error: Exception) -> ErrorCategory:
    """Classify exceptions into error categories."""
    error_str = str(error).lower()
    
    # Network errors
    if any(keyword in error_str for keyword in [
        "connection", "network", "timeout", "dns", "refused"
    ]):
        return ErrorCategory.NETWORK
    
    # Rate limiting
    if any(keyword in error_str for keyword in [
        "rate limit", "429", "too many requests"
    ]):
        return ErrorCategory.RATE_LIMIT
    
    # Timeout
    if "timeout" in error_str:
        return ErrorCategory.TIMEOUT
    
    # Validation
    if any(keyword in error_str for keyword in [
        "validation", "invalid", "malformed", "syntax"
    ]):
        return ErrorCategory.VALIDATION
    
    # Database errors
    if any(keyword in error_str for keyword in [
        "database", "sql", "connection", "deadlock"
    ]):
        return ErrorCategory.TRANSIENT  # Most DB errors are transient
    
    # Default to transient
    return ErrorCategory.TRANSIENT


def handle_a2a_error(error: Exception) -> AOPError:
    """Convert A2A protocol errors to AOP errors."""
    error_str = str(error).lower()
    
    if "timeout" in error_str:
        return TimeoutError(f"A2A call timeout: {error}", timeout=60.0)
    
    if "connection" in error_str or "network" in error_str:
        return NetworkError(f"A2A network error: {error}")
    
    if "not found" in error_str or "404" in error_str:
        return AgentError(
            f"Agent not found: {error}",
            category=ErrorCategory.AGENT_UNAVAILABLE,
            retryable=False
        )
    
    # Default classification
    category = classify_error(error)
    return AOPError(
        f"A2A error: {error}",
        category=category,
        retryable=category != ErrorCategory.VALIDATION
    )


# Global circuit breakers for common services
_circuit_breakers: Dict[str, CircuitBreaker] = {}

def get_circuit_breaker(service: str) -> CircuitBreaker:
    """Get or create circuit breaker for a service."""
    if service not in _circuit_breakers:
        _circuit_breakers[service] = CircuitBreaker()
    return _circuit_breakers[service]


def reset_circuit_breakers() -> None:
    """Reset all circuit breakers (useful for testing)."""
    global _circuit_breakers
    _circuit_breakers = {}