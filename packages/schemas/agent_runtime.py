"""Agent Runtime Interface - Standard lifecycle and health management.

This module provides the base interface and utilities for standardizing agent
runtime behavior across AOP reference agents.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class AgentHealth:
    """Agent health status."""

    status: str  # "ok" | "degraded" | "unhealthy"
    agent: str
    version: str
    uptime_seconds: float = 0.0
    startup_time: str = ""
    last_check: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, agent: str, version: str, **details: Any) -> AgentHealth:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            status="ok",
            agent=agent,
            version=version,
            startup_time=now,
            last_check=now,
            details=details,
        )

    @classmethod
    def degraded(cls, agent: str, version: str, reason: str, **details: Any) -> AgentHealth:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            status="degraded",
            agent=agent,
            version=version,
            startup_time=now,
            last_check=now,
            details={"reason": reason, **details},
        )

    @classmethod
    def unhealthy(cls, agent: str, version: str, reason: str, **details: Any) -> AgentHealth:
        now = datetime.now(timezone.utc).isoformat()
        return cls(
            status="unhealthy",
            agent=agent,
            version=version,
            startup_time=now,
            last_check=now,
            details={"reason": reason, **details},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "agent": self.agent,
            "version": self.version,
            "uptime_seconds": self.uptime_seconds,
            "startup_time": self.startup_time,
            "last_check": self.last_check,
            "details": self.details,
        }


class AgentRuntimeInterface(ABC):
    """Standard interface for agent runtime lifecycle.

    Agents should implement this interface to ensure consistent
    startup, health checking, and shutdown behavior.
    """

    @abstractmethod
    async def startup(self) -> None:
        """Initialize agent resources and prepare for serving requests."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully shutdown agent and cleanup resources."""
        pass

    @abstractmethod
    def health(self) -> AgentHealth:
        """Return current health status of the agent."""
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if agent is ready to accept requests."""
        pass

    @abstractmethod
    def get_agent_card(self) -> dict[str, Any]:
        """Return the agent's Agent Card as a dictionary."""
        pass


class BaseAgentRuntime(AgentRuntimeInterface):
    """Base implementation of AgentRuntimeInterface with common functionality.

    Provides default implementations for common patterns while requiring
    subclasses to implement agent-specific behavior.
    """

    def __init__(self) -> None:
        self._startup_time: datetime | None = None
        self._ready = False
        self._shutdown = False

    async def startup(self) -> None:
        """Default startup implementation: mark ready time."""
        self._startup_time = datetime.now(timezone.utc)
        self._ready = True
        self._shutdown = False
        logger.info(f"Agent {self.__class__.__name__} started at {self._startup_time}")

    async def shutdown(self) -> None:
        """Default shutdown implementation: mark shutdown and cleanup."""
        self._ready = False
        self._shutdown = True
        logger.info(f"Agent {self.__class__.__name__} shutdown")

    def health(self) -> AgentHealth:
        """Default health check: report basic status."""
        if self._shutdown:
            return AgentHealth.unhealthy(
                agent=self.__class__.__name__,
                version=self._get_version(),
                reason="Agent has been shut down",
            )
        if not self._ready:
            return AgentHealth.degraded(
                agent=self.__class__.__name__,
                version=self._get_version(),
                reason="Agent is not ready",
            )
        
        uptime = 0.0
        if self._startup_time:
            uptime = (datetime.now(timezone.utc) - self._startup_time).total_seconds()
        
        return AgentHealth.ok(
            agent=self.__class__.__name__,
            version=self._get_version(),
            uptime_seconds=uptime,
        )

    def is_ready(self) -> bool:
        """Check if agent is ready to accept requests."""
        return self._ready and not self._shutdown

    def get_agent_card(self) -> dict[str, Any]:
        """Return the agent's Agent Card as a dictionary."""
        raise NotImplementedError("Subclasses must implement get_agent_card")

    def _get_version(self) -> str:
        """Get agent version (override in subclasses)."""
        return "0.0.0"


class AgentLifecycleManager:
    """Manages agent lifecycle with standardized hooks."""

    def __init__(self, runtime: AgentRuntimeInterface):
        self.runtime = runtime

    async def start(self) -> None:
        """Start the agent with proper lifecycle management."""
        try:
            await self.runtime.startup()
            logger.info(f"Agent {self.runtime.__class__.__name__} lifecycle: started")
        except Exception as exc:
            logger.error(f"Agent startup failed: {exc}")
            raise

    async def stop(self) -> None:
        """Stop the agent with proper cleanup."""
        try:
            await self.runtime.shutdown()
            logger.info(f"Agent {self.runtime.__class__.__name__} lifecycle: stopped")
        except Exception as exc:
            logger.error(f"Agent shutdown failed: {exc}")
            raise

    def check_health(self) -> AgentHealth:
        """Check agent health status."""
        try:
            return self.runtime.health()
        except Exception as exc:
            logger.error(f"Health check failed: {exc}")
            return AgentHealth.unhealthy(
                agent=self.runtime.__class__.__name__,
                version="unknown",
                reason=f"Health check error: {exc}",
            )


__all__ = [
    "AgentHealth",
    "AgentRuntimeInterface",
    "BaseAgentRuntime",
    "AgentLifecycleManager",
]
