from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

AGENT_CARD_PATHS = (
    "/.well-known/agent-card.json",
    "/.well-known/agent.json",
)


@dataclass
class AgentSkill:
    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    input_modes: list[str] = field(default_factory=list)
    output_modes: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentSkill:
        return cls(
            id=raw.get("id") or raw.get("skill_id") or "",
            name=raw.get("name") or "",
            description=raw.get("description") or "",
            tags=list(raw.get("tags") or []),
            examples=list(raw.get("examples") or []),
            input_modes=list(raw.get("inputModes") or raw.get("input_modes") or []),
            output_modes=list(raw.get("outputModes") or raw.get("output_modes") or []),
        )


@dataclass
class AgentCard:
    name: str
    description: str
    url: str
    version: str
    protocol_version: str = "0.3.0"
    capabilities: dict[str, Any] = field(default_factory=dict)
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text"])
    skills: list[AgentSkill] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def skill_ids(self) -> list[str]:
        return [s.id for s in self.skills if s.id]

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentCard:
        skills = [AgentSkill.from_dict(s) for s in raw.get("skills", [])]
        return cls(
            name=raw.get("name") or "",
            description=raw.get("description") or "",
            url=raw.get("url") or "",
            version=raw.get("version") or "0.0.0",
            protocol_version=str(raw.get("protocolVersion") or raw.get("protocol_version") or "0.3.0"),
            capabilities=dict(raw.get("capabilities") or {}),
            default_input_modes=list(
                raw.get("defaultInputModes") or raw.get("default_input_modes") or ["text"]
            ),
            default_output_modes=list(
                raw.get("defaultOutputModes") or raw.get("default_output_modes") or ["text"]
            ),
            skills=skills,
            raw=raw,
        )


def _normalize_base(url: str) -> str:
    return url.rstrip("/")


def fetch_agent_card(base_url: str, timeout: float = 10.0) -> AgentCard:
    """Fetch Agent Card from well-known paths (canonical then legacy)."""
    base = _normalize_base(base_url)
    errors: list[str] = []

    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        for path in AGENT_CARD_PATHS:
            url = f"{base}{path}"
            try:
                resp = client.get(url)
                if resp.status_code == 404:
                    errors.append(f"{path}: 404")
                    continue
                resp.raise_for_status()
                data = resp.json()
                card = AgentCard.from_dict(data)
                if not card.url:
                    card.url = f"{base}/"
                return card
            except Exception as exc:  # noqa: BLE001 — collect and raise aggregate
                errors.append(f"{path}: {exc}")

    raise LookupError(
        f"Failed to fetch Agent Card from {base}. Tried {list(AGENT_CARD_PATHS)}. "
        f"Errors: {'; '.join(errors)}"
    )
