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

# Preferred default agent (agent_key). Override via DEFAULT_AGENT.
_DEFAULT_AGENTS = (
    "claude-code",
    "deepseek-harness",
    "pi",
)


def pick_agent(available: set[str], *candidates: str) -> str | None:
    """Return the first candidate agent_key present in ``available``."""
    for key in candidates:
        if key in available:
            return key
    return None


def default_agent(available: set[str]) -> str | None:
    preferred = (os.getenv("DEFAULT_AGENT") or "claude-code").strip()
    # Legacy env aliases
    if not preferred or preferred == "claude-code":
        preferred = (
            os.getenv("DEFAULT_RESEARCH_AGENT")
            or os.getenv("DEFAULT_CODE_AGENT")
            or preferred
        ).strip()
        if preferred in {"claude-researcher", "claude-coder"}:
            preferred = "claude-code"
    ordered = (preferred,) + tuple(a for a in _DEFAULT_AGENTS if a != preferred)
    return pick_agent(available, *ordered)


def wants_all_agents(goal: str) -> bool:
    """True when the goal asks to involve every available harness agent."""
    low = (goal or "").lower()
    if any(m.lower() in low for m in _MULTI_AGENT_MARKERS):
        return True
    # Explicitly names ≥2 known harness products
    named = [a for a in _DEFAULT_AGENTS if a in low or a.replace("-", " ") in low]
    if "deepseek" in low and "claude" in low:
        return True
    if "deepseek" in low and "pi" in low:
        return True
    if len(named) >= 2:
        return True
    return False


def parallel_harness_nodes(available: set[str], *, hitl: set[str]) -> list[PlanNode]:
    """One independent DAG node per online harness agent (fan-out, no deps).

    When only one agent remains after filtering, still returns a single node so
    the multi-agent intent degrades gracefully instead of failing.
    """
    keys = [a for a in _DEFAULT_AGENTS if a in available]
    if not keys:
        keys = sorted(available)
    if not keys:
        return []
    id_by_key = {
        "claude-code": "claude",
        "deepseek-harness": "deepseek",
        "pi": "pi",
    }
    nodes: list[PlanNode] = []
    used_ids: set[str] = set()
    for key in keys:
        nid = id_by_key.get(key) or key.replace("-", "_")[:24]
        base = nid
        n = 2
        while nid in used_ids:
            nid = f"{base}{n}"
            n += 1
        used_ids.add(nid)
        nodes.append(
            PlanNode(
                id=nid,
                skill=key,
                depends_on=[],
                requires_approval=key in hitl,
            )
        )
    return nodes


def probe_agent_ready(endpoint: str, *, timeout_s: float = 2.0) -> bool:
    """GET ``/health`` — treat missing flag as ready (older agents)."""
    if os.getenv("PLANNER_SKIP_READY_PROBE", "").lower() in {"1", "true", "yes"}:
        return True
    url = (endpoint or "").rstrip("/") + "/health"
    try:
        import httpx

        r = httpx.get(url, timeout=timeout_s)
        if r.status_code >= 400:
            return False
        data = r.json() if r.content else {}
        if not isinstance(data, dict):
            return True
        if "runner_ready" in data:
            return bool(data.get("runner_ready"))
        return True
    except Exception:  # noqa: BLE001
        # Unreachable → do not schedule (avoids guaranteed failure).
        return False


# Back-compat aliases
pick_skill = pick_agent
default_research_skill = default_agent
default_research_agent = default_agent
default_code_agent = default_agent

_SIMPLE_QA_MARKERS = (
    "一句话",
    "一句话介绍",
    "是什么",
    "什么是",
    "简述",
    "简短",
    "简单介绍",
)

# User explicitly wants every online harness agent in the plan.
_MULTI_AGENT_MARKERS = (
    "所有agent",
    "所有 agent",
    "全部agent",
    "全部 agent",
    "所有的agent",
    "使用目前所有",
    "用目前所有",
    "目前所有的agent",
    "目前所有agent",
    "多智能体",
    "多 agent",
    "多agent",
    "三个agent",
    "三个 agent",
    "all agents",
    "all agent",
    "every agent",
    "use all",
    "所有智能体",
    "全部智能体",
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

        available = set(self.list_available_agents())
        hitl = set(hitl_skills())
        method = "heuristic"
        nodes: list[PlanNode] = []

        # 1) Explicit multi-agent fan-out (all *ready* online harness agents)
        if wants_all_agents(goal):
            ready = set(self.list_ready_agents(available))
            multi = parallel_harness_nodes(ready or available, hitl=hitl)
            if multi:
                nodes = multi
                method = "heuristic_multi"


        # 2) Opt-in multi-step decompose (still single-agent hops unless step skills differ)
        if (
            not nodes
            and _planner_v2()
            and os.getenv("PLANNER_MULTI_STEP", "").lower() in {"1", "true", "yes"}
        ):
            stepped = decompose_to_nodes(goal, available, hitl=hitl)
            if stepped:
                nodes = stepped
                method = "heuristic_steps"

        # 3) Default single-hop heuristic (plan node.skill = agent_key)
        if not nodes:
            nodes = self._heuristic_nodes(goal, available)
            method = "heuristic"

        # 4) Optional LLM — skip when user already forced multi-agent fan-out
        if (
            method != "heuristic_multi"
            and os.getenv("PLANNER_LLM", "").lower() in {"1", "true", "yes"}
        ):
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

        # 5) Last-resort fallback → default harness agent
        if not nodes:
            agent = default_agent(available)
            if agent:
                nodes = [PlanNode(id="run", skill=agent)]
            elif available:
                key = sorted(available)[0]
                nodes = [PlanNode(id="step1", skill=key)]
            else:
                raise ValueError("no online agents registered; cannot plan")
            method = "fallback"

        plan = TaskPlan(title=title or _short_title(goal), goal=goal, nodes=nodes)
        validate_plan(plan, available_skills=available)
        return PlannerResult(plan=plan, method=method, available_skills=sorted(available))

    def list_available_agents(self) -> list[str]:
        """Online agent_keys (skills removed — route by agent)."""
        sql = """
            SELECT a.agent_key
            FROM agents a
            WHERE a.tenant_id = %s::uuid
              AND a.status IN ('online', 'running')
              AND EXISTS (
                SELECT 1 FROM agent_endpoints e
                WHERE e.agent_id = a.id AND e.is_primary = true
              )
            ORDER BY a.agent_key
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (self.tenant_id,)).fetchall()
        return [r["agent_key"] for r in rows if r.get("agent_key")]

    def list_agent_endpoints(self) -> dict[str, str]:
        """Map online agent_key → primary endpoint URL."""
        sql = """
            SELECT a.agent_key, e.url
            FROM agents a
            JOIN agent_endpoints e ON e.agent_id = a.id AND e.is_primary = true
            WHERE a.tenant_id = %s::uuid
              AND a.status IN ('online', 'running')
            ORDER BY a.agent_key
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (self.tenant_id,)).fetchall()
        out: dict[str, str] = {}
        for r in rows:
            key = r.get("agent_key")
            url = r.get("url")
            if key and url:
                out[str(key)] = str(url)
        return out

    def list_ready_agents(self, available: set[str] | None = None) -> list[str]:
        """Online agents whose ``/health`` reports runner_ready (or older agents without the flag)."""
        keys = set(available) if available is not None else set(self.list_available_agents())
        endpoints = self.list_agent_endpoints()
        ready: list[str] = []
        for key in sorted(keys):
            ep = endpoints.get(key)
            if not ep:
                continue
            if probe_agent_ready(ep):
                ready.append(key)
        return ready

    def list_available_skills(self) -> list[str]:
        """Deprecated alias — returns online agent_keys."""
        return self.list_available_agents()

    def _heuristic_nodes(self, goal: str, available: set[str]) -> list[PlanNode]:
        """Default: one hop to preferred agent; multi-agent goals fan out in parallel."""
        hitl = set(hitl_skills())
        if wants_all_agents(goal):
            ready = set(self.list_ready_agents(available))
            multi = parallel_harness_nodes(ready or available, hitl=hitl)
            if multi:
                return multi
        agent = default_agent(available)
        if not agent:
            return []
        return [
            PlanNode(
                id="run",
                skill=agent,  # task_nodes.skill stores target agent_key
                depends_on=[],
                requires_approval=agent in hitl,
            )
        ]

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
                            "Return JSON with key nodes. Only use available skills "
                            "(each skill is an agent_key). Prefer parallel independent "
                            "nodes. Keep 2-5 nodes. When the goal asks to use all agents "
                            "/ 所有agent / 全部智能体, create one parallel node per "
                            "available agent_key with empty depends_on."
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
