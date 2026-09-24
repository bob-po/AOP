"""Phase 5.4 — Capability model + matching (extends Router skills/modes)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Capability:
    skill: str = ""
    input_types: list[str] = field(default_factory=lambda: ["text"])
    output_types: list[str] = field(default_factory=lambda: ["text"])
    models: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    streaming: bool = False
    browsing: bool = False
    execution: bool = False  # code execution
    gpu: bool = False
    max_context: int = 0
    modalities: list[str] = field(default_factory=lambda: ["text"])
    version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_agent_card(cls, agent: dict[str, Any], skill: str | None = None) -> "Capability":
        caps = agent.get("capabilities") or agent.get("card") or {}
        if isinstance(caps, str):
            caps = {}
        skills = agent.get("skills") or caps.get("skills") or []
        resources = caps.get("resources") or agent.get("resources") or {}
        return cls(
            skill=skill or (skills[0] if skills else ""),
            input_types=list(
                caps.get("input_modes")
                or caps.get("inputModes")
                or (["text"] if not caps.get("input_type") else [caps["input_type"]])
            ),
            output_types=list(
                caps.get("output_modes")
                or caps.get("outputModes")
                or (["text"] if not caps.get("output_type") else [caps["output_type"]])
            ),
            models=list(caps.get("models") or []),
            tools=list(caps.get("tools") or []),
            streaming=bool(caps.get("streaming")),
            browsing=bool(caps.get("web_browsing") or caps.get("webBrowsing")),
            execution=bool(caps.get("code_execution") or caps.get("codeExecution")),
            gpu=bool(caps.get("gpu") or resources.get("gpuRequired") or resources.get("gpu")),
            max_context=int(caps.get("max_context") or caps.get("maxContext") or 0),
            modalities=list(caps.get("modalities") or ["text"]),
            version=str(caps.get("version") or agent.get("version") or "1"),
        )


@dataclass
class Requirement:
    skill: str = ""
    input_types: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    models: list[str] = field(default_factory=list)
    require_streaming: bool = False
    require_browsing: bool = False
    require_execution: bool = False
    require_gpu: bool = False
    modalities: list[str] = field(default_factory=list)
    min_context: int = 0
    version_constraint: str = ""  # Phase 6: e.g. ">=2.0.0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Requirement":
        data = data or {}
        return cls(
            skill=str(data.get("skill") or ""),
            input_types=list(data.get("input_types") or data.get("input_modes") or []),
            output_types=list(data.get("output_types") or data.get("output_modes") or []),
            models=list(data.get("models") or []),
            require_streaming=bool(data.get("require_streaming") or data.get("streaming")),
            require_browsing=bool(data.get("require_browsing") or data.get("browsing")),
            require_execution=bool(data.get("require_execution") or data.get("code_execution")),
            require_gpu=bool(data.get("require_gpu") or data.get("gpu")),
            modalities=list(data.get("modalities") or []),
            min_context=int(data.get("min_context") or 0),
            version_constraint=str(
                data.get("version_constraint") or data.get("version") or ""
            ),
        )


def capability_match(req: Requirement, cap: Capability) -> tuple[bool, str, float]:
    """Return (ok, reason, score 0..1)."""
    score = 0.0
    weights = 0.0

    if req.skill:
        weights += 1
        skills_ok = True
        # skill may be on agent separately; Capability.skill is primary
        if cap.skill and req.skill != cap.skill:
            # allow empty skill on cap when matched externally
            if cap.skill not in {req.skill}:
                skills_ok = False
        if not skills_ok and req.skill:
            # soft: if skill forced elsewhere, don't fail here when cap.skill blank
            if cap.skill:
                return False, f"skill_mismatch:{cap.skill}", 0.0
        score += 1.0

    def _subset(need: list[str], have: list[str], label: str) -> tuple[bool, str]:
        if not need:
            return True, "ok"
        if not have:
            return True, "unspecified"  # legacy agents
        missing = [x for x in need if x not in have]
        if missing:
            return False, f"{label}_missing:{missing}"
        return True, "ok"

    ok, reason = _subset(req.input_types, cap.input_types, "input")
    if not ok:
        return False, reason, 0.0
    ok, reason = _subset(req.output_types, cap.output_types, "output")
    if not ok:
        return False, reason, 0.0
    ok, reason = _subset(req.modalities, cap.modalities, "modality")
    if not ok:
        return False, reason, 0.0
    if req.models:
        if cap.models and not set(req.models) & set(cap.models):
            return False, "model_mismatch", 0.0
        score += 0.2
    if req.require_streaming and not cap.streaming:
        return False, "streaming_required", 0.0
    if req.require_browsing and not cap.browsing:
        return False, "browsing_required", 0.0
    if req.require_execution and not cap.execution:
        return False, "execution_required", 0.0
    if req.require_gpu and not cap.gpu:
        return False, "gpu_required", 0.0
    if req.min_context and cap.max_context and cap.max_context < req.min_context:
        return False, "context_too_small", 0.0
    if req.version_constraint:
        try:
            from marketplace.deps import satisfies

            if not satisfies(cap.version or "0.0.0", req.version_constraint):
                return False, f"version_mismatch:{cap.version}", 0.0
            score += 0.1
        except Exception:  # noqa: BLE001
            pass

    # Soft bonuses
    if cap.gpu:
        score += 0.05
    if cap.streaming:
        score += 0.05
    return True, "ok", min(1.0, 0.7 + score)


def filter_by_capability(
    candidates: list[dict[str, Any]],
    requirement: Requirement,
    *,
    skill_field: str = "skills",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter agent dicts; attaches capability_score. Skill membership checked here."""
    passed, excluded = [], []
    for c in candidates:
        skills = set(c.get(skill_field) or [])
        if requirement.skill and requirement.skill not in skills and c.get("skill") != requirement.skill:
            excluded.append({"agent_id": c.get("agent_id"), "reason": "skill_absent"})
            continue
        cap = Capability.from_agent_card(c, skill=requirement.skill)
        # Prefer matched_version from Phase 6 discovery when present
        if c.get("matched_version"):
            cap.version = str(c["matched_version"])
        elif c.get("version"):
            cap.version = str(c["version"])
        ok, reason, score = capability_match(requirement, cap)
        if not ok:
            excluded.append({"agent_id": c.get("agent_id"), "reason": reason})
            continue
        enriched = {**c, "capability_score": score, "capability": cap.to_dict()}
        passed.append(enriched)
    return passed, excluded


__all__ = [
    "Capability",
    "Requirement",
    "capability_match",
    "filter_by_capability",
]
