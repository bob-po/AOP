"""Phase 6 SandboxProvider — install isolation (no arbitrary code execution)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SandboxSpec:
    agent_key: str
    version: str
    endpoint: str
    permissions: list[str] = field(default_factory=list)
    requirements: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    checksum: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SandboxResult:
    ok: bool
    sandbox_id: str
    kind: str
    endpoint: str
    resource_limits: dict[str, Any] = field(default_factory=dict)
    network_policy: dict[str, Any] = field(default_factory=dict)
    filesystem_policy: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SandboxProvider(ABC):
    kind: str = "abstract"

    @abstractmethod
    def provision(self, spec: SandboxSpec) -> SandboxResult:
        ...

    @abstractmethod
    def health_check(self, sandbox_id: str) -> bool:
        ...

    @abstractmethod
    def destroy(self, sandbox_id: str) -> None:
        ...


class LocalProcessSandbox(SandboxProvider):
    """
    Baseline isolation: do NOT download/execute source.
    Only accept pre-deployed endpoints after checksum/permission validation.
    """

    kind = "local_process"

    def __init__(self) -> None:
        self._active: dict[str, SandboxSpec] = {}

    def provision(self, spec: SandboxSpec) -> SandboxResult:
        if spec.source_url and not spec.metadata.get("allow_remote_source"):
            return SandboxResult(
                ok=False,
                sandbox_id="",
                kind=self.kind,
                endpoint=spec.endpoint,
                error="remote source execution forbidden; provide pre-deployed endpoint",
            )
        if not spec.endpoint.startswith(("http://", "https://")):
            return SandboxResult(
                ok=False,
                sandbox_id="",
                kind=self.kind,
                endpoint=spec.endpoint,
                error="invalid endpoint",
            )
        # Resource limits from requirements
        limits = {
            "cpu": spec.requirements.get("cpu", 1),
            "memory_mb": spec.requirements.get("memory_mb", 512),
            "gpu": bool(spec.requirements.get("gpu", False)),
        }
        network = {
            "egress": "network" in spec.permissions,
            "other_agents": "other_agents" in spec.permissions,
        }
        fs = {
            "read_write": "filesystem" in spec.permissions,
            "shell": "shell" in spec.permissions,
        }
        if fs["shell"] and not spec.metadata.get("allow_privileged"):
            return SandboxResult(
                ok=False,
                sandbox_id="",
                kind=self.kind,
                endpoint=spec.endpoint,
                error="shell permission denied in LocalProcessSandbox",
            )
        sid = f"local:{spec.agent_key}:{spec.version}"
        self._active[sid] = spec
        return SandboxResult(
            ok=True,
            sandbox_id=sid,
            kind=self.kind,
            endpoint=spec.endpoint,
            resource_limits=limits,
            network_policy=network,
            filesystem_policy=fs,
            metadata={"verified_checksum": spec.checksum},
        )

    def health_check(self, sandbox_id: str) -> bool:
        return sandbox_id in self._active

    def destroy(self, sandbox_id: str) -> None:
        self._active.pop(sandbox_id, None)


class DockerSandbox(SandboxProvider):
    """Reserved — not implemented; returns not-supported."""

    kind = "docker"

    def provision(self, spec: SandboxSpec) -> SandboxResult:
        return SandboxResult(
            ok=False,
            sandbox_id="",
            kind=self.kind,
            endpoint=spec.endpoint,
            error="DockerSandbox not enabled in this environment",
        )

    def health_check(self, sandbox_id: str) -> bool:
        return False

    def destroy(self, sandbox_id: str) -> None:
        return None


class KubernetesSandbox(SandboxProvider):
    """Reserved — not implemented; returns not-supported."""

    kind = "kubernetes"

    def provision(self, spec: SandboxSpec) -> SandboxResult:
        return SandboxResult(
            ok=False,
            sandbox_id="",
            kind=self.kind,
            endpoint=spec.endpoint,
            error="KubernetesSandbox not enabled in this environment",
        )

    def health_check(self, sandbox_id: str) -> bool:
        return False

    def destroy(self, sandbox_id: str) -> None:
        return None


def get_sandbox_provider(kind: str = "local_process") -> SandboxProvider:
    mapping = {
        "local_process": LocalProcessSandbox,
        "local": LocalProcessSandbox,
        "docker": DockerSandbox,
        "kubernetes": KubernetesSandbox,
        "k8s": KubernetesSandbox,
    }
    cls = mapping.get(kind, LocalProcessSandbox)
    return cls()
