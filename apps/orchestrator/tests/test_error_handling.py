"""Worker-adjacent pure tests: retry policy + circuit breaker."""

from __future__ import annotations

import pytest

from error_handling import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    ErrorCategory,
    RetryPolicy,
    classify_error,
    with_retry,
)


def test_retry_policy_succeeds_after_transient_failures():
    calls = {"n": 0}

    @with_retry(
        policy=RetryPolicy(max_attempts=3, base_delay=0.0, exponential_base=1.0, jitter=False)
    )
    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("temporary")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_circuit_breaker_opens_after_threshold():
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
    failures = 0

    def boom():
        nonlocal failures
        failures += 1
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker.call(boom)

    assert breaker.state == "open"
    before = failures
    with pytest.raises(CircuitBreakerOpenError):
        breaker.call(boom)
    assert failures == before  # boom not invoked while open


def test_classify_network_and_validation():
    assert classify_error(Exception("connection refused")) == ErrorCategory.NETWORK
    assert classify_error(Exception("invalid payload")) == ErrorCategory.VALIDATION
