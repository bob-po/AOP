"""Phase 6 Agent Manifest — validation + normalization."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

ALLOWED_PERMISSIONS = frozenset(
    {
        "network",
        "filesystem",
        "gpu",
        "database",
        "shell",
        "external_api",
        "other_agents",
    }
)

_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


class ManifestValidationError(ValueError):
    pass


@dataclass
class AgentManifest:
    name: str
    version: str
    description: str = ""
    author: str = ""
    runtime: dict[str, Any] = field(default_factory=dict)
    endpoint: str = ""
    protocol: str = "a2a"
    capabilities: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    requirements: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    dependencies: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "runtime": self.runtime,
            "endpoint": self.endpoint or self.runtime.get("endpoint", ""),
            "protocol": self.protocol or self.runtime.get("protocol", "a2a"),
            "capabilities": list(self.capabilities),
            "skills": list(self.skills),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "requirements": dict(self.requirements),
            "permissions": list(self.permissions),
            "dependencies": dict(self.dependencies),
            "metadata": dict(self.metadata),
        }

    def checksum(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_str_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise ManifestValidationError(f"{field_name} must be a list")
    out: list[str] = []
    for item in value:
        s = str(item).strip()
        if not s:
            raise ManifestValidationError(f"{field_name} contains empty entry")
        out.append(s)
    return out


def _normalize_permissions(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        # {"network": true, "filesystem": false}
        out = [k for k, v in value.items() if v]
    elif isinstance(value, list):
        out = [str(x).strip() for x in value if str(x).strip()]
    else:
        raise ManifestValidationError("permissions must be list or object")
    bad = [p for p in out if p not in ALLOWED_PERMISSIONS]
    if bad:
        raise ManifestValidationError(f"illegal permissions: {bad}")
    return sorted(set(out))


def parse_manifest(data: dict[str, Any] | AgentManifest) -> AgentManifest:
    if isinstance(data, AgentManifest):
        return data
    if not isinstance(data, dict):
        raise ManifestValidationError("manifest must be an object")

    name = str(data.get("name") or "").strip()
    version = str(data.get("version") or "").strip()
    if not name:
        raise ManifestValidationError("name is required")
    if not version:
        raise ManifestValidationError("version is required")
    if not _SEMVER.match(version):
        raise ManifestValidationError(f"version must be semver: {version}")

    runtime = data.get("runtime") or {}
    if runtime is not None and not isinstance(runtime, dict):
        raise ManifestValidationError("runtime must be an object")
    runtime = dict(runtime or {})

    endpoint = str(data.get("endpoint") or runtime.get("endpoint") or "").strip()
    protocol = str(data.get("protocol") or runtime.get("protocol") or "a2a").strip().lower()
    if protocol != "a2a":
        raise ManifestValidationError(f"unsupported protocol: {protocol}")
    if not endpoint:
        raise ManifestValidationError("endpoint (or runtime.endpoint) is required")
    if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        raise ManifestValidationError("endpoint must be http(s) URL")

    deps = data.get("dependencies") or {}
    if deps is not None and not isinstance(deps, dict):
        raise ManifestValidationError("dependencies must be an object")

    requirements = data.get("requirements") or {}
    if requirements is not None and not isinstance(requirements, dict):
        raise ManifestValidationError("requirements must be an object")

    metadata = data.get("metadata") or {}
    if metadata is not None and not isinstance(metadata, dict):
        raise ManifestValidationError("metadata must be an object")

    return AgentManifest(
        name=name,
        version=version,
        description=str(data.get("description") or ""),
        author=str(data.get("author") or data.get("publisher") or ""),
        runtime=runtime,
        endpoint=endpoint,
        protocol=protocol,
        capabilities=_as_str_list(data.get("capabilities"), "capabilities"),
        skills=_as_str_list(data.get("skills"), "skills"),
        inputs=_as_str_list(data.get("inputs"), "inputs"),
        outputs=_as_str_list(data.get("outputs"), "outputs"),
        requirements=dict(requirements or {}),
        permissions=_normalize_permissions(data.get("permissions")),
        dependencies=dict(deps or {}),
        metadata=dict(metadata or {}),
    )


def validate_manifest(data: dict[str, Any] | AgentManifest) -> AgentManifest:
    """Validate and return normalized AgentManifest. Raises ManifestValidationError."""
    m = parse_manifest(data)
    # Security: reject shell+filesystem without explicit metadata flag (soft policy).
    if "shell" in m.permissions and "filesystem" in m.permissions:
        if not m.metadata.get("allow_privileged"):
            raise ManifestValidationError(
                "shell+filesystem requires metadata.allow_privileged=true"
            )
    return m
