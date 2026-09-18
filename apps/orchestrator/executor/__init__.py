"""Executor: invoke a remote A2A agent and normalize artifacts (sandbox-aware)."""

from __future__ import annotations

import logging
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

    def discover(self, agent_url: str) -> AgentCard:
        client = A2AClient(agent_url, timeout=self.timeout)
        return client.card

    def execute(
        self,
        agent_url: str,
        query: str,
        *,
        skill_id: str | None = None,
    ) -> ExecutionResult:
        try:
            q, timeout = guard_call(
                endpoint=agent_url,
                skill=skill_id,
                query=query,
                policy=self.policy,
            )
            client = A2AClient(agent_url, timeout=timeout)
            card = client.card
            task = client.send_text(q, skill_id=skill_id)
            text = clamp_output(first_text_artifact(task), self.policy)
            return ExecutionResult(
                agent_name=card.name,
                agent_url=agent_url.rstrip("/"),
                skill_id=skill_id,
                task=task,
                text=text,
                data=first_data_artifact(task),
            )
        except SandboxViolation:
            raise
        except Exception as e:
            if ERROR_HANDLING_AVAILABLE:
                aop_error = handle_a2a_error(e)
                logger.error(f"A2A execution error: {aop_error.to_dict()}")
                raise aop_error from e
            logger.error(f"A2A execution error: {e}")
            raise
