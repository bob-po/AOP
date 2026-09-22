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

_SIMPLE_QA_MARKERS = (
    "一句话",
    "一句话介绍",
    "是什么",
    "什么是",
    "简述",
    "简短",
    "简单介绍",
)
_REPORT_INTENT = (
    "报告",
    "report",
    "总结",
    "summary",
    "调研",
    "生成报告",
)
_PPT_INTENT = (
    "ppt",
    "pptx",
    "powerpoint",
    "幻灯片",
    "演示文稿",
    "课件",
    "生成ppt",
    "做个ppt",
    "做一份ppt",
)
_SEARCH_INTENT = (
    "搜索",
    "检索",
    "查找",
    "搜一下",
    "search",
    "什么是",
    "是什么",
)
_RAG_INTENT = (
    "知识库",
    "rag",
    "资料库",
    "本地文档",
    "文档库",
)
_ANALYSIS_INTENT = (
    "分析",
    "对比",
    "比较",
    "研判",
    "综述",
)
_DEEP_RESEARCH = (
    "调研",
    "研究",
    "深入",
    "全面了解",
    "深度",
)
_RESEARCH_EXCLUDE_FROM_SIMPLE = (
    "报告",
    "report",
    "ppt",
    "pptx",
    "幻灯片",
    "演示文稿",
    "总结",
    "summary",
    "调研",
    "分析并",
    "生成报告",
)
_MEDIA_EXCLUDE_FROM_SIMPLE = (
    "图",
    "image",
    "宣传图",
    "海报",
    "插画",
    "视频",
    "video",
    "短片",
    "宣传片",
)


def _wants_report(goal: str) -> bool:
    text = (goal or "").lower()
    return any(k in text for k in _REPORT_INTENT)


def _wants_ppt(goal: str) -> bool:
    text = (goal or "").lower()
    return any(k in text for k in _PPT_INTENT)


def _wants_search(goal: str) -> bool:
    text = (goal or "").lower()
    return any(k in text for k in _SEARCH_INTENT)


def _wants_rag(goal: str) -> bool:
    text = (goal or "").lower()
    return any(k in text for k in _RAG_INTENT)


def _wants_analysis(goal: str) -> bool:
    return any(k in (goal or "") for k in _ANALYSIS_INTENT)


def _wants_deep_research(goal: str) -> bool:
    return any(k in (goal or "") for k in _DEEP_RESEARCH)


def _is_simple_qa(goal: str) -> bool:
    """True for short factual / one-sentence questions — search only, no report DAG."""
    text = (goal or "").strip()
    if not text:
        return False
    lower = text.lower()
    if any(k in lower for k in _RESEARCH_EXCLUDE_FROM_SIMPLE):
        return False
    if any(k in text for k in _MEDIA_EXCLUDE_FROM_SIMPLE):
        return False
    if any(k in text for k in ("分析", "对比", "比较", "研究", "调研")):
        return False
    if any(k in text for k in _SIMPLE_QA_MARKERS):
        return True
    compact = re.sub(r"\s+", "", text)
    if len(compact) > 28:
        return False
    return bool(re.search(r"(什么|吗|呢|\?|？)$", compact) or "什么" in compact)


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
        """Build a *minimal* intent DAG — do not dump the full research pipeline."""
        text = goal.lower()
        wants_report = _wants_report(goal)
        wants_ppt = _wants_ppt(goal)
        wants_search = _wants_search(goal)
        wants_rag = _wants_rag(goal)
        wants_analysis = _wants_analysis(goal)
        deep = _wants_deep_research(goal)
        wants_image = any(k in text for k in ("图", "image", "宣传图", "海报", "插画"))
        wants_video = any(k in text for k in ("视频", "video", "短片", "宣传片"))
        hitl = set(hitl_skills())

        # Intro PPT without deep research / analysis / report → search→ppt only.
        thin_intro_ppt = (
            wants_ppt
            and not wants_report
            and not wants_analysis
            and not deep
            and not wants_rag
        )

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

        # Short factual Q&A → web-search only (DeerFlow/Bing already answer in-band).
        if _is_simple_qa(goal):
            try_add("search", "web-search", ())
            return list(created.values())

        # Pure media generation (no research / report / ppt wording).
        researchish = (
            wants_search
            or wants_rag
            or wants_analysis
            or wants_report
            or wants_ppt
            or deep
        )
        if (wants_image or wants_video) and not researchish:
            if wants_image:
                try_add("image", "text-to-image", ())
            if wants_video:
                try_add("video", "text-to-video", ())
            return list(created.values())

        # --- gather context only when needed ---
        need_search = (
            wants_search
            or wants_report
            or wants_ppt
            or wants_analysis
            or deep
            or (not created and not wants_image and not wants_video)
        )
        if need_search:
            try_add("search", "web-search", ())

        # RAG: explicit ask, or deep research (not thin intro PPT).
        if wants_rag or (deep and not thin_intro_ppt):
            try_add("rag", "knowledge-search", ())

        # Analysis: explicit, report pipeline, or deep research (not thin PPT).
        if wants_analysis or wants_report or (deep and not thin_intro_ppt):
            analysis_deps = tuple(n for n in ("search", "rag") if n in created)
            try_add("analysis", "business-analysis", analysis_deps)

        if wants_report:
            report_deps: tuple[str, ...] = (
                ("analysis",) if "analysis" in created else tuple(created.keys())
            )
            try_add("report", "report-generation", report_deps)

        if wants_ppt:
            if "analysis" in created:
                ppt_deps: tuple[str, ...] = ("analysis",)
            elif "search" in created:
                ppt_deps = ("search",)
            elif "rag" in created:
                ppt_deps = ("rag",)
            else:
                ppt_deps = ()
            try_add("ppt", "ppt-generation", ppt_deps)

        media_deps = tuple(
            n for n in ("search", "rag", "analysis", "report", "ppt") if n in created
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
