"""Normalize / repair planner JSON payloads (Phase 19)."""

from __future__ import annotations

import json
import re
from typing import Any

from .dag import PlanNode

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from raw model output (fences / leading junk OK)."""
    raw = (text or "").strip()
    if not raw:
        return None
    candidates: list[str] = [raw]
    m = _FENCE_RE.search(raw)
    if m:
        candidates.insert(0, m.group(1).strip())
    # Slice from first { to last }
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])

    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
        if isinstance(data, list):
            return {"nodes": data}
    return None


def nodes_from_payload(
    data: dict[str, Any],
    *,
    available_skills: set[str],
    hitl: set[str],
    max_nodes: int = 8,
) -> list[PlanNode]:
    """Coerce LLM/heuristic JSON into PlanNodes; drop illegal skills/deps."""
    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, list):
        return []

    built: list[PlanNode] = []
    seen_ids: set[str] = set()

    for i, item in enumerate(raw_nodes):
        if len(built) >= max_nodes:
            break
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()
        if skill not in available_skills:
            # allow alias: skill_id with spaces
            alt = skill.replace(" ", "-")
            if alt in available_skills:
                skill = alt
            else:
                continue
        node_id = str(item.get("id") or f"step{i + 1}").strip()
        node_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", node_id) or f"step{i + 1}"
        if node_id in seen_ids:
            node_id = f"{node_id}_{i + 1}"
        seen_ids.add(node_id)

        deps_raw = item.get("depends_on") or []
        if isinstance(deps_raw, str):
            deps_raw = [deps_raw]
        if not isinstance(deps_raw, list):
            deps_raw = []
        deps = [str(d).strip() for d in deps_raw if str(d).strip()]

        requires = bool(item.get("requires_approval")) or skill in hitl
        built.append(
            PlanNode(
                id=node_id,
                skill=skill,
                depends_on=deps,
                requires_approval=requires,
            )
        )

    if not built:
        return []

    id_set = {n.id for n in built}
    # Drop unknown deps; drop self-deps
    for n in built:
        n.depends_on = [d for d in n.depends_on if d in id_set and d != n.id]

    # Break simple 2-cycles by clearing later node's edge
    by_id = {n.id: n for n in built}
    for n in built:
        for d in list(n.depends_on):
            other = by_id.get(d)
            if other and n.id in other.depends_on:
                # keep earlier dependency only
                if built.index(n) > built.index(other):
                    n.depends_on = [x for x in n.depends_on if x != d]
                else:
                    other.depends_on = [x for x in other.depends_on if x != n.id]

    return built
