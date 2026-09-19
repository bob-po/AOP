"""PlanningEngine: thin application-facing wrapper over Planner."""

from __future__ import annotations

from typing import Any

from . import Planner, PlannerResult


class PlanningEngine:
    """Natural-language goal → validated TaskPlan (delegates to Planner)."""

    def __init__(self, planner: Planner | None = None, **kwargs: Any) -> None:
        self._planner = planner or Planner(**kwargs)

    @property
    def planner(self) -> Planner:
        return self._planner

    def plan(self, goal: str, *, title: str | None = None) -> PlannerResult:
        return self._planner.plan(goal, title=title)

    def list_available_skills(self) -> list[str]:
        return self._planner.list_available_skills()
