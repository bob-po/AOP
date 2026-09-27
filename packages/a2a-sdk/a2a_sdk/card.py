from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from .protocol import PROTOCOL_VERSION

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

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
        }
        if self.tags:
            payload["tags"] = list(self.tags)
        if self.examples:
            payload["examples"] = list(self.examples)
        if self.input_modes:
            payload["inputModes"] = list(self.input_modes)
        if self.output_modes:
            payload["outputModes"] = list(self.output_modes)
        return payload

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
    protocol_version: str = PROTOCOL_VERSION
    capabilities: dict[str, Any] = field(default_factory=dict)
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text"])
    skills: list[AgentSkill] = field(default_factory=list)
    preferred_transport: str | None = None
    additional_interfaces: list[dict[str, Any]] = field(default_factory=list)
    security_schemes: dict[str, Any] = field(default_factory=dict)
    security: list[Any] = field(default_factory=list)
    supports_authenticated_extended_card: bool = False
    extensions: list[dict[str, Any]] = field(default_factory=list)
    provider: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def skill_ids(self) -> list[str]:
        return [s.id for s in self.skills if s.id]

    def supports_streaming(self) -> bool:
        return bool((self.capabilities or {}).get("streaming"))

    def supports_push(self) -> bool:
        return bool((self.capabilities or {}).get("pushNotifications"))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": self.protocol_version or PROTOCOL_VERSION,
            "capabilities": dict(self.capabilities or {}),
            "defaultInputModes": list(self.default_input_modes),
            "defaultOutputModes": list(self.default_output_modes),
            "skills": [s.to_dict() for s in self.skills],
        }
        if self.preferred_transport:
            payload["preferredTransport"] = self.preferred_transport
        if self.additional_interfaces:
            payload["additionalInterfaces"] = list(self.additional_interfaces)
        if self.security_schemes:
            payload["securitySchemes"] = dict(self.security_schemes)
        if self.security:
            payload["security"] = list(self.security)
        if self.supports_authenticated_extended_card:
            payload["supportsAuthenticatedExtendedCard"] = True
        if self.extensions:
            payload["extensions"] = list(self.extensions)
        if self.provider:
            payload["provider"] = dict(self.provider)
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentCard:
        skills = [AgentSkill.from_dict(s) for s in raw.get("skills", [])]
        return cls(
            name=raw.get("name") or "",
            description=raw.get("description") or "",
            url=raw.get("url") or "",
            version=raw.get("version") or "0.0.0",
            protocol_version=str(
                raw.get("protocolVersion") or raw.get("protocol_version") or PROTOCOL_VERSION
            ),
            capabilities=dict(raw.get("capabilities") or {}),
            default_input_modes=list(
                raw.get("defaultInputModes") or raw.get("default_input_modes") or ["text"]
            ),
            default_output_modes=list(
                raw.get("defaultOutputModes") or raw.get("default_output_modes") or ["text"]
            ),
            skills=skills,
            preferred_transport=raw.get("preferredTransport") or raw.get("preferred_transport"),
            additional_interfaces=list(
                raw.get("additionalInterfaces") or raw.get("additional_interfaces") or []
            ),
            security_schemes=dict(
                raw.get("securitySchemes") or raw.get("security_schemes") or {}
            ),
            security=list(raw.get("security") or []),
            supports_authenticated_extended_card=bool(
                raw.get("supportsAuthenticatedExtendedCard")
                or raw.get("supports_authenticated_extended_card")
            ),
            extensions=list(raw.get("extensions") or []),
            provider=raw.get("provider") if isinstance(raw.get("provider"), dict) else None,
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
