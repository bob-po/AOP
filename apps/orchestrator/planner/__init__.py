"""Planner: natural language goal → Task DAG (skill-based). Phase 19 = v2."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.rows import dict_row
from db import connect

from .dag import DAGValidationError, PlanNode, TaskPlan, validate_plan
from .decompose import decompose_to_nodes
from .json_plan import extract_json_object, nodes_from_payload
from router import hitl_skills

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Preferred research pipeline when skills exist in registry.
PIPELINE: list[tuple[str, str, tuple[str, ...]]] = [
    ("search", "web-search", ()),
    ("rag", "knowledge-search", ()),
    ("analysis", "business-analysis", ("search", "rag")),
    ("report", "report-generation", ("analysis",)),
]


@dataclass
class PlannerResult:
    plan: TaskPlan
    method: str  # heuristic | heuristic_steps | llm | llm_repaired | fallback
    available_skills: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "available_skills": self.available_skills,
            "plan": self.plan.to_dict(),
        }


class Planner:
    def __init__(
        self,
        database_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.tenant_id = tenant_id

    def plan(self, goal: str, *, title: str | None = None) -> PlannerResult:
        goal = (goal or "").strip()
        if not goal:
            raise ValueError("goal is required")

        available = set(self.list_available_skills())
        hitl = set(hitl_skills())
        method = "heuristic"
        nodes: list[PlanNode] = []

        # 1) Multi-step wording → linear DAG (Phase 19)
        if _planner_v2():
            stepped = decompose_to_nodes(goal, available, hitl=hitl)
            if stepped:
                nodes = stepped
                method = "heuristic_steps"

        # 2) Default research / media heuristic
        if not nodes:
            nodes = self._heuristic_nodes(goal, available)
            method = "heuristic"

        # 3) Optional LLM — validate or repair; never fail hard (Phase 19)
        if os.getenv("PLANNER_LLM", "").lower() in {"1", "true", "yes"}:
            llm_nodes, repaired = self._try_llm_nodes(goal, available, hitl=hitl)
            if llm_nodes:
                try:
                    trial = TaskPlan(
                        title=title or _short_title(goal),
                        goal=goal,
                        nodes=llm_nodes,
                    )
                    validate_plan(trial, available_skills=available)
                    nodes = llm_nodes
                    method = "llm_repaired" if repaired else "llm"
                except DAGValidationError:
                    pass  # keep heuristic / steps

        # 4) Last-resort fallback
        if not nodes:
            if "web-search" in available:
                nodes = [PlanNode(id="search", skill="web-search")]
            elif available:
                skill = sorted(available)[0]
                nodes = [PlanNode(id="step1", skill=skill)]
            else:
                raise ValueError("no online agents/skills registered; cannot plan")
            method = "fallback"

        plan = TaskPlan(title=title or _short_title(goal), goal=goal, nodes=nodes)
        validate_plan(plan, available_skills=available)
        return PlannerResult(plan=plan, method=method, available_skills=sorted(available))

    def list_available_skills(self) -> list[str]:
        sql = """
            SELECT DISTINCT s.skill_id
            FROM agent_skills s
            JOIN agents a ON a.id = s.agent_id
            WHERE a.tenant_id = %s::uuid
              AND a.status IN ('online', 'running')
            ORDER BY s.skill_id
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (self.tenant_id,)).fetchall()
        return [r["skill_id"] for r in rows]

    def _heuristic_nodes(self, goal: str, available: set[str]) -> list[PlanNode]:
        text = goal.lower()
        wants_report = any(
            k in text for k in ("报告", "report", "ppt", "总结", "summary", "生成")
        )
        hitl = set(hitl_skills())

        created: dict[str, PlanNode] = {}

        def try_add(node_id: str, skill: str, depends_on: tuple[str, ...]) -> None:
            if skill not in available or node_id in created:
                return
            deps = [d for d in depends_on if d in created]
            created[node_id] = PlanNode(
                id=node_id,
                skill=skill,
                depends_on=deps,
                requires_approval=skill in hitl,
            )

        try_add("search", "web-search", ())
        try_add("rag", "knowledge-search", ())
        try_add("analysis", "business-analysis", ("search", "rag"))

        if "report-generation" in available and (wants_report or len(created) >= 1):
            if "analysis" in created:
                deps: tuple[str, ...] = ("analysis",)
            else:
                deps = tuple(created.keys())
            try_add("report", "report-generation", deps)

        wants_image = any(k in text for k in ("图", "image", "宣传图", "海报", "插画"))
        wants_video = any(k in text for k in ("视频", "video", "短片", "宣传片"))
        media_deps = tuple(
            n for n in ("search", "rag", "analysis", "report") if n in created
        ) or ()
        if wants_image:
            try_add("image", "text-to-image", media_deps)
        if wants_video:
            try_add("video", "text-to-video", media_deps)

        if not created:
            for skill in sorted(available):
                token = skill.replace("-", " ")
                if skill in text or token in text:
                    try_add(skill, skill, ())

        return list(created.values())

    def _try_llm_nodes(
        self,
        goal: str,
        available: set[str],
        *,
        hitl: set[str],
    ) -> tuple[list[PlanNode] | None, bool]:
        """Returns (nodes, repaired). nodes is None on hard miss."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None, False
        try:
            from openai import OpenAI
        except ImportError:
            return None, False

        client = OpenAI(api_key=api_key, base_url=os.getenv("OPENAI_BASE_URL") or None)
        model = os.getenv("PLANNER_MODEL", "gpt-4o-mini")
        prompt = {
            "goal": goal,
            "available_skills": sorted(available),
            "schema": {
                "nodes": [
                    {
                        "id": "string",
                        "skill": "must be in available_skills",
                        "depends_on": ["node_id"],
                    }
                ]
            },
        }
        try:
            resp = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a task planner for a multi-agent platform. "
                            "Return JSON with key nodes. Only use available skills. "
                            "Prefer parallel independent nodes. Keep 2-5 nodes."
                        ),
                    },
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
            )
            content = resp.choices[0].message.content or "{}"
        except Exception:  # noqa: BLE001
            return None, False

        data = extract_json_object(content)
        if not data:
            return None, False

        repaired = False
        try:
            # Strict path: expect clean nodes
            raw_nodes = data.get("nodes") or []
            if not isinstance(raw_nodes, list) or not raw_nodes:
                return None, False
            nodes: list[PlanNode] = []
            for n in raw_nodes:
                if not isinstance(n, dict):
                    repaired = True
                    continue
                skill = str(n.get("skill") or "")
                nodes.append(
                    PlanNode(
                        id=str(n.get("id") or "node"),
                        skill=skill,
                        depends_on=[str(d) for d in (n.get("depends_on") or [])],
                        requires_approval=bool(n.get("requires_approval"))
                        or skill in hitl,
                    )
                )
            trial = TaskPlan(title="t", goal=goal, nodes=nodes)
            validate_plan(trial, available_skills=available)
            return nodes, repaired
        except (DAGValidationError, KeyError, TypeError, ValueError):
            repaired = True
            fixed = nodes_from_payload(data, available_skills=available, hitl=hitl)
            if not fixed:
                return None, False
            try:
                validate_plan(
                    TaskPlan(title="t", goal=goal, nodes=fixed),
                    available_skills=available,
                )
            except DAGValidationError:
                return None, False
            return fixed, True


def _planner_v2() -> bool:
    # Default on; set PLANNER_V2=0 to disable step decomposition
    return os.getenv("PLANNER_V2", "1").lower() not in {"0", "false", "no", "off"}


def _short_title(goal: str, limit: int = 48) -> str:
    cleaned = re.sub(r"\s+", " ", goal).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "..."
