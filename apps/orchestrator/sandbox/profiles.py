"""Seccomp / high-risk skill profile registry (Phase 27)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Skills that must run on dedicated hardened agents
HIGH_RISK_SKILLS: frozenset[str] = frozenset(
    {
        "code-execution",
        "browser-automation",
    }
)

# Endpoint hostnames permitted for high-risk skills
HIGH_RISK_HOSTS: frozenset[str] = frozenset(
    {
        "code-agent",
        "browser-agent",
        "127.0.0.1",
        "localhost",
    }
)

SKILL_TO_HOST: dict[str, str] = {
    "code-execution": "code-agent",
    "browser-automation": "browser-agent",
}

SKILL_TO_PROFILE: dict[str, str] = {
    "code-execution": "code-agent.json",
    "browser-automation": "browser-agent.json",
}

DEFAULT_PROFILE = "agent-hardened.json"


def high_risk_allowed() -> bool:
    """Gate for scheduling high-risk skills (default on in compose)."""
    return os.getenv("AGENT_ALLOW_HIGH_RISK", "1").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def is_high_risk_skill(skill: str | None) -> bool:
    return (skill or "").strip() in HIGH_RISK_SKILLS


def profile_for_skill(skill: str | None) -> str:
    skill = (skill or "").strip()
    return SKILL_TO_PROFILE.get(skill, DEFAULT_PROFILE)


def seccomp_dir() -> Path:
    override = os.getenv("AOP_SECCOMP_DIR", "").strip()
    if override:
        return Path(override)
    # deployments/seccomp relative to repo root
    here = Path(__file__).resolve()
    return here.parents[3] / "deployments" / "seccomp"


def load_profile(name: str) -> dict[str, Any]:
    path = seccomp_dir() / name
    return json.loads(path.read_text(encoding="utf-8"))


def validate_profiles() -> list[str]:
    """Return list of profile basenames that parse and have defaultAction."""
    d = seccomp_dir()
    ok: list[str] = []
    for path in sorted(d.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "defaultAction" in data, path.name
        assert "syscalls" in data, path.name
        ok.append(path.name)
    return ok


def check_high_risk_endpoint(skill: str | None, endpoint: str) -> None:
    """Raise SandboxViolation if high-risk skill is not on a dedicated host."""
    from sandbox import SandboxViolation  # local import avoids cycle at module load

    skill = (skill or "").strip()
    if not is_high_risk_skill(skill):
        return
    if not high_risk_allowed():
        raise SandboxViolation(
            f"high-risk skill disabled (set AGENT_ALLOW_HIGH_RISK=1): {skill}"
        )
    host = (urlparse(endpoint).hostname or "").lower()
    expected = SKILL_TO_HOST.get(skill)
    allowed = {expected, "127.0.0.1", "localhost"} if expected else set(HIGH_RISK_HOSTS)
    if host not in allowed:
        raise SandboxViolation(
            f"high-risk skill {skill} requires host {expected}/localhost, got {host}"
        )
