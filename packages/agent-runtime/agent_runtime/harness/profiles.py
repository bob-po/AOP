"""Canonical harness virtual-agent profile table (single source of truth).

Ports / keys / default runners for:
- ``scripts/start_and_register_agents.py``
- ``marketplace`` catalog + bundle ports
- router host→localhost remapping
- aop-node ``plugins/*/plugin.toml`` (keep in sync manually; values live here)

Specialty coder/researcher splits are gone — one row per product.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import Iterable


@dataclass(frozen=True)
class HarnessProfile:
    key: str
    port: int
    runner: str
    name: str
    description: str
    tags: tuple[str, ...] = ()
    env_url_key: str = ""

    @property
    def package_id(self) -> str:
        return f"pkg-{self.key}"

    @property
    def default_endpoint(self) -> str:
        return f"http://127.0.0.1:{self.port}"


HARNESS_PROFILES: tuple[HarnessProfile, ...] = (
    HarnessProfile(
        key="claude-code",
        port=8011,
        runner="claude_cli",
        name="Claude Code Agent",
        description="Unified Claude Code harness agent",
        tags=("harness", "claude"),
        env_url_key="AOP_AGENT_CLAUDE_CODE_URL",
    ),
    HarnessProfile(
        key="deepseek-harness",
        port=8012,
        runner="deepseek",
        name="DeepSeek Harness Agent",
        description="Unified DeepSeek Harness agent",
        tags=("harness", "deepseek"),
        env_url_key="AOP_AGENT_DEEPSEEK_HARNESS_URL",
    ),
    HarnessProfile(
        key="pi",
        port=8013,
        runner="pi_cli",
        name="Pi Agent",
        description="Unified Pi harness agent",
        tags=("harness", "pi"),
        env_url_key="AOP_AGENT_PI_URL",
    ),
    HarnessProfile(
        key="openclaw",
        port=8014,
        runner="openclaw",
        name="OpenClaw Agent",
        description="Unified OpenClaw harness agent (agent exec)",
        tags=("harness", "openclaw"),
        env_url_key="AOP_AGENT_OPENCLAW_URL",
    ),
    HarnessProfile(
        key="hermes",
        port=8015,
        runner="hermes",
        name="Hermes Agent",
        description="Unified Hermes Agent harness (hermes chat)",
        tags=("harness", "hermes"),
        env_url_key="AOP_AGENT_HERMES_URL",
    ),
)


def profile_by_key(key: str) -> HarnessProfile | None:
    k = (key or "").strip().lower()
    for p in HARNESS_PROFILES:
        if p.key == k:
            return p
    return None


def default_ports() -> dict[str, int]:
    return {p.key: p.port for p in HARNESS_PROFILES}


def host_port_map() -> dict[str, int]:
    """Docker service host names → local ports (plus harness-agent alias)."""
    m = default_ports()
    m["harness-agent"] = 8011
    return m


def as_port_tuples() -> list[tuple[str, int]]:
    return [(p.key, p.port) for p in HARNESS_PROFILES]


def marketplace_catalog_rows(
    *,
    endpoint_resolver: Callable[[str, str], str] | None = None,
) -> list[dict]:
    """Build marketplace CATALOG dicts from the profile table."""

    def _ep(env_key: str, fallback: str) -> str:
        if endpoint_resolver is not None:
            return str(endpoint_resolver(env_key, fallback)).rstrip("/")
        import os

        return (os.getenv(env_key) or fallback).rstrip("/")

    rows: list[dict] = []
    for p in HARNESS_PROFILES:
        rows.append(
            {
                "package_id": p.package_id,
                "name": p.name,
                "description": p.description,
                "publisher": "AOP Official",
                "version": "0.1.0",
                "skills": [],
                "default_endpoint": _ep(p.env_url_key, p.default_endpoint),
                "agent_key": p.key,
                "tags": list(p.tags),
            }
        )
    return rows


__all__ = [
    "HarnessProfile",
    "HARNESS_PROFILES",
    "profile_by_key",
    "default_ports",
    "host_port_map",
    "as_port_tuples",
    "marketplace_catalog_rows",
]
