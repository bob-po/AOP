"""Goal decomposition into ordered skill steps (Phase 19)."""

from __future__ import annotations

import re

from .dag import PlanNode

# (keywords, skill) — first match wins per fragment
_SKILL_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("视频", "video", "短片", "宣传片"), "text-to-video"),
    (("图", "image", "海报", "插画", "宣传图"), "text-to-image"),
    (("报告", "report", "ppt", "总结", "summary"), "report-generation"),
    (("分析", "analysis", "研判"), "business-analysis"),
    (("知识库", "rag", "文档", "资料库"), "knowledge-search"),
    (("搜索", "search", "检索", "查找", "调研", "研究"), "web-search"),
]

_SPLIT_RE = re.compile(
    r"(?:"
    r"\d+[\.\)、]\s*"  # 1. / 1) / 1、
    r"|首先|然后|接着|其次|最后|再者"
    r"|先\s*|再\s*|然后\s*"
    r"|\bthen\b|\bafter that\b|\band then\b"
    r"|；|;|\n+"
    r")",
    re.IGNORECASE,
)


def split_goal_fragments(goal: str) -> list[str]:
    text = (goal or "").strip()
    if not text:
        return []
    parts = [p.strip(" \t\r\n-—·•") for p in _SPLIT_RE.split(text)]
    return [p for p in parts if len(p) >= 2]


def skill_for_fragment(fragment: str, available: set[str]) -> str | None:
    low = fragment.lower()
    for keys, skill in _SKILL_HINTS:
        if skill not in available:
            continue
        if any(k.lower() in low for k in keys):
            return skill
    return None


def decompose_to_nodes(
    goal: str,
    available: set[str],
    *,
    hitl: set[str],
    max_nodes: int = 6,
) -> list[PlanNode]:
    """Build a linear DAG from multi-step wording when ≥2 fragments map to skills."""
    frags = split_goal_fragments(goal)
    if len(frags) < 2:
        return []

    steps: list[tuple[str, str]] = []  # (id, skill)
    used_skills: list[str] = []
    for i, frag in enumerate(frags):
        skill = skill_for_fragment(frag, available)
        if not skill:
            continue
        # avoid immediate duplicate skill spam
        if used_skills and used_skills[-1] == skill and skill != "web-search":
            continue
        node_id = f"step{len(steps) + 1}"
        # prefer canonical ids for first occurrence of pipeline skills
        canon = {
            "web-search": "search",
            "knowledge-search": "rag",
            "business-analysis": "analysis",
            "report-generation": "report",
            "text-to-image": "image",
            "text-to-video": "video",
        }.get(skill)
        if canon and canon not in {s[0] for s in steps}:
            node_id = canon
        steps.append((node_id, skill))
        used_skills.append(skill)
        if len(steps) >= max_nodes:
            break

    if len(steps) < 2:
        return []

    nodes: list[PlanNode] = []
    prev: str | None = None
    for node_id, skill in steps:
        deps = [prev] if prev else []
        nodes.append(
            PlanNode(
                id=node_id,
                skill=skill,
                depends_on=deps,
                requires_approval=skill in hitl,
            )
        )
        prev = node_id
    return nodes
