"""RoutingEngine: thin application-facing wrapper over AgentRouter."""

from __future__ import annotations

from typing import Any

from . import AgentRouter, RoutedAgent


class RoutingEngine:
    """Skill → scored online agent selection (delegates to AgentRouter)."""

    def __init__(self, router: AgentRouter | None = None, **kwargs: Any) -> None:
        self._router = router or AgentRouter(**kwargs)

    @property
    def router(self) -> AgentRouter:
        return self._router

    def select(
        self,
        skill: str,
        *,
        exclude_agent_ids: set[str] | list[str] | None = None,
    ) -> RoutedAgent:
        return self._router.select(skill, exclude_agent_ids=exclude_agent_ids)

    def rank(
        self,
        skill: str,
        *,
        exclude_agent_ids: set[str] | list[str] | None = None,
    ) -> list[RoutedAgent]:
        return self._router.rank(skill, exclude_agent_ids=exclude_agent_ids)

    def preview(
        self,
        skill: str,
        *,
        exclude_agent_ids: set[str] | list[str] | None = None,
    ) -> dict[str, Any]:
        return self._router.preview(skill, exclude_agent_ids=exclude_agent_ids)

    def agent_performance(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return self._router.agent_performance(limit=limit)

    def discover(self, **kwargs: Any) -> dict[str, Any]:
        """Capability-aware discovery — open to any Agent (A2A OS)."""
        return self._router.discover(**kwargs)

    def route(self, **kwargs: Any) -> dict[str, Any]:
        """Select the best Agent for a request — open to any Agent (A2A OS)."""
        return self._router.route(**kwargs)
