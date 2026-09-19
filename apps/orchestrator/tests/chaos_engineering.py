"""Chaos engineering and failure injection tests (P36.7).

This module provides chaos engineering capabilities for testing
system resilience under failure conditions.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable


class FailureType(Enum):
    """Types of failures to inject."""
    NETWORK_DELAY = "network_delay"
    NETWORK_FAILURE = "network_failure"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_ERROR = "agent_error"
    DATABASE_FAILURE = "database_failure"
    HIGH_LATENCY = "high_latency"
    DUPLICATE_REQUEST = "duplicate_request"


@dataclass
class FailureScenario:
    """A failure scenario to inject."""
    name: str
    failure_type: FailureType
    probability: float = 0.1
    delay_ms: int = 0
    error_message: str = "Injected failure"
    apply_to: list[str] = None  # List of agent IDs or skills to apply to
    
    def __post_init__(self):
        if self.apply_to is None:
            self.apply_to = []


class ChaosEngine:
    """Chaos engineering engine for failure injection."""
    
    def __init__(self):
        self.scenarios: list[FailureScenario] = []
        self.enabled = False
        self.injection_count = 0
    
    def add_scenario(self, scenario: FailureScenario) -> None:
        """Add a failure scenario."""
        self.scenarios.append(scenario)
    
    def enable(self) -> None:
        """Enable chaos engineering."""
        self.enabled = True
    
    def disable(self) -> None:
        """Disable chaos engineering."""
        self.enabled = False
    
    def should_inject_failure(
        self,
        agent_id: str | None = None,
        skill: str | None = None,
    ) -> tuple[bool, FailureScenario | None]:
        """Check if a failure should be injected."""
        if not self.enabled:
            return False, None
        
        for scenario in self.scenarios:
            # Check if scenario applies to this agent/skill
            if scenario.apply_to:
                if agent_id and agent_id not in scenario.apply_to:
                    continue
                if skill and skill not in scenario.apply_to:
                    continue
            
            # Check probability
            if random.random() < scenario.probability:
                self.injection_count += 1
                return True, scenario
        
        return False, None
    
    def inject_network_delay(self, delay_ms: int) -> None:
        """Inject network delay."""
        time.sleep(delay_ms / 1000.0)
    
    def inject_agent_timeout(self) -> None:
        """Simulate agent timeout."""
        time.sleep(65.0)  # Longer than default 60s timeout
    
    def inject_agent_error(self, error_message: str) -> Exception:
        """Inject agent error."""
        return RuntimeError(error_message)
    
    def inject_duplicate_request(self) -> None:
        """Simulate duplicate request delivery."""
        # This is handled by the caller making duplicate calls
        pass
    
    def get_injection_stats(self) -> dict[str, Any]:
        """Get injection statistics."""
        return {
            "enabled": self.enabled,
            "total_injections": self.injection_count,
            "active_scenarios": len(self.scenarios),
        }


class FailureInjectionDecorator:
    """Decorator for injecting failures into function calls."""
    
    def __init__(self, chaos_engine: ChaosEngine):
        self.chaos_engine = chaos_engine
    
    def __call__(
        self,
        agent_id: str | None = None,
        skill: str | None = None,
    ):
        """Decorator factory."""
        def decorator(func: Callable) -> Callable:
            def wrapper(*args, **kwargs):
                # Check if failure should be injected
                should_inject, scenario = self.chaos_engine.should_inject_failure(
                    agent_id=agent_id,
                    skill=skill,
                )
                
                if should_inject and scenario:
                    if scenario.failure_type == FailureType.NETWORK_DELAY:
                        self.chaos_engine.inject_network_delay(scenario.delay_ms)
                    elif scenario.failure_type == FailureType.AGENT_TIMEOUT:
                        self.chaos_engine.inject_agent_timeout()
                    elif scenario.failure_type == FailureType.AGENT_ERROR:
                        raise self.chaos_engine.inject_agent_error(scenario.error_message)
                    elif scenario.failure_type == FailureType.HIGH_LATENCY:
                        self.chaos_engine.inject_network_delay(scenario.delay_ms)
                
                return func(*args, **kwargs)
            return wrapper
        return decorator


class StressTestRunner:
    """Stress test runner for system load testing."""
    
    def __init__(self):
        self.results: list[dict[str, Any]] = []
    
    def run_concurrent_tasks(
        self,
        task_count: int,
        concurrent_limit: int,
        task_func: Callable,
    ) -> dict[str, Any]:
        """Run concurrent tasks with stress load."""
        import concurrent.futures
        
        start_time = time.time()
        successful = 0
        failed = 0
        errors = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_limit) as executor:
            futures = [executor.submit(task_func, i) for i in range(task_count)]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    future.result()
                    successful += 1
                except Exception as e:
                    failed += 1
                    errors.append(str(e))
        
        duration = time.time() - start_time
        
        result = {
            "task_count": task_count,
            "concurrent_limit": concurrent_limit,
            "successful": successful,
            "failed": failed,
            "duration": duration,
            "throughput": task_count / duration if duration > 0 else 0,
            "errors": errors[:10],  # Keep only first 10 errors
        }
        
        self.results.append(result)
        return result
    
    def get_results_summary(self) -> dict[str, Any]:
        """Get summary of all stress test results."""
        if not self.results:
            return {"total_tests": 0}
        
        total_successful = sum(r["successful"] for r in self.results)
        total_failed = sum(r["failed"] for r in self.results)
        avg_throughput = sum(r["throughput"] for r in self.results) / len(self.results)
        
        return {
            "total_tests": len(self.results),
            "total_successful": total_successful,
            "total_failed": total_failed,
            "success_rate": total_successful / (total_successful + total_failed) if (total_successful + total_failed) > 0 else 0,
            "avg_throughput": avg_throughput,
        }


# Singleton instances
_chaos_engine: ChaosEngine | None = None
_stress_test_runner: StressTestRunner | None = None


def get_chaos_engine() -> ChaosEngine:
    """Get or create the singleton chaos engine."""
    global _chaos_engine
    if _chaos_engine is None:
        _chaos_engine = ChaosEngine()
    return _chaos_engine


def get_stress_test_runner() -> StressTestRunner:
    """Get or create the singleton stress test runner."""
    global _stress_test_runner
    if _stress_test_runner is None:
        _stress_test_runner = StressTestRunner()
    return _stress_test_runner
