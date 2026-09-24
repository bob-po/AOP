"""Candidate Filter for Router v3 - Multi-stage agent filtering.

This module provides filtering logic for capability-aware agent selection,
supporting capability matching, input/output compatibility, health, resources,
tenant/permission, and policy-based filtering.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

ONLINE_STATUSES = frozenset({"online", "running"})


@dataclass
class FilterResult:
    """Result of a filtering stage."""

    stage: str
    total: int
    passed: int
    excluded: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "total": self.total,
            "passed": self.passed,
            "excluded": self.excluded,
        }


@dataclass
class FilterStats:
    """Statistics for the complete filtering pipeline."""

    skill_match: FilterResult
    capability_match: FilterResult
    mode_compatibility: FilterResult
    health_filter: FilterResult
    resource_filter: FilterResult
    tenant_filter: FilterResult
    policy_filter: FilterResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_match": self.skill_match.to_dict(),
            "capability_match": self.capability_match.to_dict(),
            "mode_compatibility": self.mode_compatibility.to_dict(),
            "health_filter": self.health_filter.to_dict(),
            "resource_filter": self.resource_filter.to_dict(),
            "tenant_filter": self.tenant_filter.to_dict(),
            "policy_filter": self.policy_filter.to_dict(),
        }


@dataclass
class TaskRequirements:
    """Task requirements for filtering."""

    skill: str
    input_modes: list[str] = field(default_factory=lambda: ["text"])
    output_modes: list[str] = field(default_factory=lambda: ["text"])
    requires_streaming: bool = False
    requires_web_browsing: bool = False
    requires_code_execution: bool = False
    required_cpu: float | None = None
    required_memory_mb: int | None = None
    requires_gpu: bool = False
    gpu_type: str | None = None
    tenant_id: str = "00000000-0000-0000-0000-000000000001"


@dataclass
class RoutingPolicy:
    """Routing policy configuration."""

    strict_health: bool = False
    cross_tenant: bool = False
    blocked_agents: list[str] = field(default_factory=list)
    allowed_agents: list[str] = field(default_factory=list)
    mode: str = "allowlist"  # allowlist | blacklist
    region: str | None = None

    @classmethod
    def default(cls) -> RoutingPolicy:
        """Create default routing policy."""
        return cls(
            strict_health=False,
            cross_tenant=False,
            blocked_agents=[],
            allowed_agents=[],
            mode="allowlist",
            region=None,
        )


class CandidateFilter:
    """Multi-stage candidate filtering for agent selection."""

    def __init__(
        self,
        policy: RoutingPolicy | None = None,
        lifecycle_checker=None,
        capacity_queue_depth=None,
    ):
        self.policy = policy or RoutingPolicy.default()
        # Phase 4: optional callables injected by orchestrator
        # lifecycle_checker(agent_id) -> (ok: bool, reason: str)
        self.lifecycle_checker = lifecycle_checker
        # capacity_queue_depth(agent_id) -> int
        self.capacity_queue_depth = capacity_queue_depth

    def filter_candidates(
        self,
        candidates: list[dict],
        requirements: TaskRequirements,
        exclude_agent_ids: set[str] | None = None,
    ) -> tuple[list[dict], FilterStats]:
        """Apply all filter stages to candidates.

        Args:
            candidates: List of agent candidates
            requirements: Task requirements
            exclude_agent_ids: Agent IDs to exclude

        Returns:
            Tuple of (filtered candidates, filter statistics)
        """
        stats = FilterStats(
            skill_match=FilterResult("skill_match", len(candidates), len(candidates)),
            capability_match=FilterResult("capability_match", 0, 0),
            mode_compatibility=FilterResult("mode_compatibility", 0, 0),
            health_filter=FilterResult("health_filter", 0, 0),
            resource_filter=FilterResult("resource_filter", 0, 0),
            tenant_filter=FilterResult("tenant_filter", 0, 0),
            policy_filter=FilterResult("policy_filter", 0, 0),
        )

        results = candidates.copy()

        # Stage 1: Skill Match (already done by caller, but track stats)
        stats.skill_match = FilterResult("skill_match", len(candidates), len(results))

        # Stage 2: Capability Match
        results, stats.capability_match = self._filter_by_capabilities(
            results, requirements
        )

        # Stage 3: Input/Output Compatibility
        results, stats.mode_compatibility = self._filter_by_modes(
            results, requirements
        )

        # Stage 4: Health Filter
        results, stats.health_filter = self._filter_by_health(results)

        # Stage 5: Resource Filter
        results, stats.resource_filter = self._filter_by_resources(
            results, requirements
        )

        # Stage 6: Tenant/Permission Filter
        results, stats.tenant_filter = self._filter_by_tenant(results, requirements)

        # Stage 7: Policy Filter
        results, stats.policy_filter = self._filter_by_policy(results)

        # Manual exclusion
        if exclude_agent_ids:
            before_count = len(results)
            results = [c for c in results if c["agent_id"] not in exclude_agent_ids]
            excluded_count = before_count - len(results)
            if excluded_count > 0:
                # Add to policy filter excluded list
                for agent_id in exclude_agent_ids:
                    if any(c["agent_id"] == agent_id for c in candidates):
                        stats.policy_filter.excluded.append({
                            "agent_id": agent_id,
                            "reason": "manually excluded",
                        })
                stats.policy_filter.passed = len(results)

        return results, stats

    def _filter_by_capabilities(
        self,
        candidates: list[dict],
        requirements: TaskRequirements,
    ) -> tuple[list[dict], FilterResult]:
        """Filter by required capabilities."""
        excluded = []
        passed = []

        for candidate in candidates:
            agent_caps = self._parse_capabilities(candidate)

            # Check streaming requirement
            if requirements.requires_streaming and not agent_caps.get("streaming", False):
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": "missing capability: streaming",
                })
                continue

            # Check web browsing requirement
            if requirements.requires_web_browsing and not agent_caps.get("web_browsing", False):
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": "missing capability: web_browsing",
                })
                continue

            # Check code execution requirement
            if requirements.requires_code_execution and not agent_caps.get("code_execution", False):
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": "missing capability: code_execution",
                })
                continue

            passed.append(candidate)

        return passed, FilterResult("capability_match", len(candidates), len(passed), excluded)

    def _filter_by_modes(
        self,
        candidates: list[dict],
        requirements: TaskRequirements,
    ) -> tuple[list[dict], FilterResult]:
        """Filter by input/output mode compatibility."""
        excluded = []
        passed = []

        for candidate in candidates:
            skill_info = self._get_skill_info(candidate, requirements.skill)
            agent_input_modes = skill_info.get("input_modes", ["text"])
            agent_output_modes = skill_info.get("output_modes", ["text"])

            # Check input mode compatibility
            if not any(mode in agent_input_modes for mode in requirements.input_modes):
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": f"incompatible input modes: required {requirements.input_modes}, has {agent_input_modes}",
                })
                continue

            # Check output mode compatibility
            if not any(mode in agent_output_modes for mode in requirements.output_modes):
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": f"incompatible output modes: required {requirements.output_modes}, has {agent_output_modes}",
                })
                continue

            passed.append(candidate)

        return passed, FilterResult("mode_compatibility", len(candidates), len(passed), excluded)

    def _filter_by_health(self, candidates: list[dict]) -> tuple[list[dict], FilterResult]:
        """Filter by health status + Phase 4 lifecycle/capacity."""
        excluded = []
        passed = []

        for candidate in candidates:
            agent_id = candidate.get("agent_id")
            status = candidate.get("status", "")

            # Online status check
            if status not in ONLINE_STATUSES:
                excluded.append({
                    "agent_id": agent_id,
                    "reason": f"not online: {status}",
                })
                continue

            # Phase 4: lifecycle READY/BUSY + capacity (legacy untracked allowed)
            if self.lifecycle_checker is not None and agent_id:
                try:
                    ok, reason = self.lifecycle_checker(agent_id)
                    if not ok:
                        excluded.append({
                            "agent_id": agent_id,
                            "reason": reason,
                        })
                        continue
                except Exception:  # noqa: BLE001
                    pass

            if self.capacity_queue_depth is not None and agent_id:
                try:
                    depth = int(self.capacity_queue_depth(agent_id) or 0)
                    candidate = {**candidate, "queue_depth": depth}
                except Exception:  # noqa: BLE001
                    pass

            passed.append(candidate)

        return passed, FilterResult("health_filter", len(candidates), len(passed), excluded)

    def _filter_by_resources(
        self,
        candidates: list[dict],
        requirements: TaskRequirements,
    ) -> tuple[list[dict], FilterResult]:
        """Filter by resource requirements."""
        excluded = []
        passed = []

        for candidate in candidates:
            agent_resources = self._parse_resources(candidate)

            # Check CPU requirement
            if requirements.required_cpu and agent_resources.get("cpu_cores", 0) < requirements.required_cpu:
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": f"insufficient CPU: required {requirements.required_cpu}, has {agent_resources.get('cpu_cores', 0)}",
                })
                continue

            # Check memory requirement
            if requirements.required_memory_mb and agent_resources.get("memory_mb", 0) < requirements.required_memory_mb:
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": f"insufficient memory: required {requirements.required_memory_mb}MB, has {agent_resources.get('memory_mb', 0)}MB",
                })
                continue

            # Check GPU requirement
            if requirements.requires_gpu and not agent_resources.get("gpu_required", False):
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": "GPU required but not available",
                })
                continue

            # Check GPU type
            if requirements.gpu_type and agent_resources.get("gpu_type") != requirements.gpu_type:
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": f"GPU type mismatch: required {requirements.gpu_type}, has {agent_resources.get('gpu_type')}",
                })
                continue

            passed.append(candidate)

        return passed, FilterResult("resource_filter", len(candidates), len(passed), excluded)

    def _filter_by_tenant(
        self,
        candidates: list[dict],
        requirements: TaskRequirements,
    ) -> tuple[list[dict], FilterResult]:
        """Filter by tenant and permissions."""
        excluded = []
        passed = []

        for candidate in candidates:
            # Tenant filter
            candidate_tenant_id = candidate.get("tenant_id", "")
            if candidate_tenant_id != requirements.tenant_id and not self.policy.cross_tenant:
                excluded.append({
                    "agent_id": candidate["agent_id"],
                    "reason": f"tenant mismatch: required {requirements.tenant_id}, has {candidate_tenant_id}",
                })
                continue

            # Permission filter (TODO: implement permission checking)
            # For now, just pass
            passed.append(candidate)

        return passed, FilterResult("tenant_filter", len(candidates), len(passed), excluded)

    def _filter_by_policy(self, candidates: list[dict]) -> tuple[list[dict], FilterResult]:
        """Filter by tenant-specific policies."""
        excluded = []
        passed = []

        for candidate in candidates:
            agent_id = candidate["agent_id"]

            # Blocked agents
            if agent_id in self.policy.blocked_agents:
                excluded.append({
                    "agent_id": agent_id,
                    "reason": "blocked by policy",
                })
                continue

            # Allowed agents (whitelist mode)
            if self.policy.mode == "allowlist" and self.policy.allowed_agents:
                if agent_id not in self.policy.allowed_agents:
                    excluded.append({
                        "agent_id": agent_id,
                        "reason": "not in whitelist",
                    })
                    continue

            # Regional policy (TODO: implement regional filtering)
            passed.append(candidate)

        return passed, FilterResult("policy_filter", len(candidates), len(passed), excluded)

    def _parse_capabilities(self, candidate: dict) -> dict[str, bool]:
        """Parse agent capabilities from card_json."""
        card_json = candidate.get("card_json") or {}
        capabilities = card_json.get("capabilities") or {}

        # Normalize capabilities
        return {
            "streaming": bool(capabilities.get("streaming", False)),
            "push_notifications": bool(capabilities.get("pushNotifications", False)),
            "web_browsing": bool(capabilities.get("webBrowsing", False)),
            "code_execution": bool(capabilities.get("codeExecution", False)),
        }

    def _parse_resources(self, candidate: dict) -> dict[str, Any]:
        """Parse agent resource requirements from card_json."""
        card_json = candidate.get("card_json") or {}
        resources = card_json.get("resources") or {}

        return {
            "cpu_cores": resources.get("cpuCores"),
            "memory_mb": resources.get("memoryMb"),
            "gpu_required": bool(resources.get("gpuRequired", False)),
            "gpu_type": resources.get("gpuType"),
        }

    def _get_skill_info(self, candidate: dict, skill_id: str) -> dict[str, Any]:
        """Get skill information from card_json."""
        card_json = candidate.get("card_json") or {}
        skills = card_json.get("skills") or []

        for skill in skills:
            if skill.get("id") == skill_id:
                return skill

        # Return default if skill not found
        return {
            "input_modes": ["text"],
            "output_modes": ["text"],
        }


__all__ = [
    "FilterResult",
    "FilterStats",
    "TaskRequirements",
    "RoutingPolicy",
    "CandidateFilter",
]
