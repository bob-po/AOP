"""Goal decomposition into ordered skill steps (Phase 19)."""

from __future__ import annotations

import re

from .dag import PlanNode

# (keywords, preferred skills) — first available skill wins per fragment
_SKILL_HINTS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("视频", "video", "短片", "宣传片"), ("text-to-video",)),
    (("图", "image", "海报", "插画", "宣传图"), ("text-to-image",)),
    (("ppt", "pptx", "幻灯片", "演示文稿", "课件", "powerpoint"), ("ppt-generation",)),
    (("报告", "report", "总结", "summary"), ("research-summarize", "report-generation")),
    (("分析", "analysis", "研判"), ("research-summarize", "business-analysis")),
    (("知识库", "rag", "文档", "资料库"), ("knowledge-search",)),
    (
        ("搜索", "search", "检索", "查找", "调研", "研究"),
        ("web-research", "web-search"),
    ),
]

_SPLIT_RE = re.compile(
    r"(?:"
    r"\d+[\.\)、]\s*"  # 1. / 1) / 1、
    r"|首先|然后|接着|其次|最后|再者"
    r"|先\s*|再\s*|然后\s*"
    r"|\bthen\b|\bafter that\b|\band then\b"
    r"|；|;|，|,|\n+"  # Chinese / English commas between actions
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
    for keys, skills in _SKILL_HINTS:
        if not any(k.lower() in low for k in keys):
            continue
        for skill in skills:
            if skill in available:
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
        # avoid immediate duplicate skill spam (allow repeated research/search)
        if used_skills and used_skills[-1] == skill and skill not in {
            "web-research",
            "web-search",
        }:
            continue
        node_id = f"step{len(steps) + 1}"
        # prefer canonical ids for first occurrence of pipeline skills
        canon = {
            "web-research": "search",
            "web-search": "search",
            "knowledge-search": "rag",
            "research-summarize": "analysis",
            "business-analysis": "analysis",
            "report-generation": "report",
            "ppt-generation": "ppt",
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
