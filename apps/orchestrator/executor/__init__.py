"""Executor: invoke a remote A2A agent and normalize artifacts (sandbox-aware)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from a2a_sdk import A2AClient, AgentCard, Task
from a2a_sdk.client import first_data_artifact, first_text_artifact

from sandbox import SandboxPolicy, SandboxViolation, clamp_output, guard_call

logger = logging.getLogger(__name__)

try:
    from error_handling import (
        handle_a2a_error,
        NetworkError,
        TimeoutError as AOPTimeoutError,
        AgentError,
    )

    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False

    def handle_a2a_error(error):
        return error

    NetworkError = None
    AOPTimeoutError = None
    AgentError = None

# Request tracking for P36.1 idempotency (lazy import to avoid circular dependency)
REQUEST_TRACKING_AVAILABLE = False


@dataclass
class ExecutionResult:
    agent_name: str
    agent_url: str
    skill_id: str | None
    task: Task
    text: str | None
    data: dict[str, Any] | None

    @property
    def ok(self) -> bool:
        return self.task.status.value == "completed"


class A2AExecutor:
    """Sync executor with Phase 22 sandbox guardrails."""

    def __init__(self, timeout: float = 60.0, policy: SandboxPolicy | None = None):
        self.timeout = timeout
        self.policy = policy

    def _get_request_tracking_service(self):
        """Lazy import of request tracking service."""
        try:
            from request_tracking import get_request_tracking_service
            return get_request_tracking_service()
        except ImportError:
            return None

    def discover(self, agent_url: str) -> AgentCard:
        client = A2AClient(agent_url, timeout=self.timeout)
        return client.card

    def execute(
        self,
        agent_url: str,
        query: str,
        *,
        skill_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> ExecutionResult:
        # P36.1: Use provided idempotency key or generate one
        if idempotency_key is None:
            idempotency_key = f"req_{uuid.uuid4().hex}"

        # P36.1: Check if request already completed (deduplication)
        service = self._get_request_tracking_service()
        if service and service.is_request_completed(idempotency_key):
            cached_response = service.get_cached_response(idempotency_key)
            if cached_response:
                logger.info(f"Returning cached response for idempotency_key={idempotency_key}")
                # Reconstruct ExecutionResult from cached response
                return self._result_from_cache(cached_response, agent_url, skill_id)

        try:
            q, timeout = guard_call(
                endpoint=agent_url,
                skill=skill_id,
                query=query,
                policy=self.policy,
            )
            client = A2AClient(agent_url, timeout=timeout)
            card = client.card
            # P36.1: Pass idempotency key to Agent
            task = client.send_text(q, skill_id=skill_id, idempotency_key=idempotency_key)
            text = clamp_output(first_text_artifact(task), self.policy)
            result = ExecutionResult(
                agent_name=card.name,
                agent_url=agent_url.rstrip("/"),
                skill_id=skill_id,
                task=task,
                text=text,
                data=first_data_artifact(task),
            )
            return result
        except SandboxViolation:
            raise
        except Exception as e:
            if ERROR_HANDLING_AVAILABLE:
                aop_error = handle_a2a_error(e)
                logger.error(f"A2A execution error: {aop_error.to_dict()}")
                raise aop_error from e
            logger.error(f"A2A execution error: {e}")
            raise

    def _result_from_cache(
        self,
        cached_response: dict[str, Any],
        agent_url: str,
        skill_id: str | None,
    ) -> ExecutionResult:
        """Reconstruct ExecutionResult from cached response."""
        # This is a simplified reconstruction - in production, you'd want to cache the full Task object
        task_dict = cached_response.get("task", {})
        task = Task.from_dict(task_dict) if task_dict else Task(
            id=cached_response.get("task_id", "cached"),
            status=cached_response.get("status", "completed"),
            artifacts=cached_response.get("artifacts", []),
        )
        return ExecutionResult(
            agent_name=cached_response.get("agent_name", "cached"),
            agent_url=agent_url.rstrip("/"),
            skill_id=skill_id,
            task=task,
            text=cached_response.get("text"),
            data=cached_response.get("data"),
        )
