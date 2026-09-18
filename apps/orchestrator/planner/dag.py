"""Task DAG models and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


class DAGValidationError(ValueError):
    pass


@dataclass
class PlanNode:
    id: str
    skill: str
    depends_on: list[str] = field(default_factory=list)
    requires_approval: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"id": self.id, "skill": self.skill}
        if self.depends_on:
            payload["depends_on"] = list(self.depends_on)
        if self.requires_approval:
            payload["requires_approval"] = True
        return payload


@dataclass
class TaskPlan:
    title: str
    goal: str
    nodes: list[PlanNode]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "goal": self.goal,
            "nodes": [n.to_dict() for n in self.nodes],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaskPlan:
        nodes = [
            PlanNode(
                id=str(n["id"]),
                skill=str(n["skill"]),
                depends_on=[str(d) for d in (n.get("depends_on") or [])],
                requires_approval=bool(n.get("requires_approval")),
            )
            for n in (raw.get("nodes") or [])
        ]
        return cls(
            title=str(raw.get("title") or "task"),
            goal=str(raw.get("goal") or ""),
            nodes=nodes,
        )


def validate_plan(plan: TaskPlan, *, available_skills: Iterable[str] | None = None) -> None:
    if not plan.nodes:
        raise DAGValidationError("plan must contain at least one node")

    ids = [n.id for n in plan.nodes]
    if any(not i or not str(i).strip() for i in ids):
        raise DAGValidationError("node id must be non-empty")
    if len(ids) != len(set(ids)):
        raise DAGValidationError("node ids must be unique")

    id_set = set(ids)
    skills_ok = set(available_skills) if available_skills is not None else None

    for node in plan.nodes:
        if not node.skill or not node.skill.strip():
            raise DAGValidationError(f"node {node.id!r} skill must be non-empty")
        if skills_ok is not None and node.skill not in skills_ok:
            raise DAGValidationError(
                f"node {node.id!r} skill {node.skill!r} is not available in registry"
            )
        for dep in node.depends_on:
            if dep not in id_set:
                raise DAGValidationError(
                    f"node {node.id!r} depends on unknown node {dep!r}"
                )
            if dep == node.id:
                raise DAGValidationError(f"node {node.id!r} cannot depend on itself")

    # Cycle detection (DFS)
    graph = {n.id: list(n.depends_on) for n in plan.nodes}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node_id: str) -> None:
        if node_id in visiting:
            raise DAGValidationError(f"cycle detected at node {node_id!r}")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dep in graph.get(node_id, []):
            dfs(dep)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in ids:
        dfs(node_id)


def ready_node_ids(nodes: list[PlanNode], completed: set[str], pending: set[str]) -> list[str]:
    """Return node ids in pending whose dependencies are all completed."""
    ready: list[str] = []
    by_id = {n.id: n for n in nodes}
    for node_id in pending:
        node = by_id[node_id]
        if all(dep in completed for dep in node.depends_on):
            ready.append(node_id)
    return ready
