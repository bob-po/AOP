"""Agent Marketplace catalog + install helpers (Phase 6 extended)."""

from __future__ import annotations

from marketplace.service import (
    CATALOG,
    DEFAULT_TENANT_ID,
    MarketplaceService,
    PKG_DEPRECATED,
    PKG_DRAFT,
    PKG_PUBLISHED,
    PKG_REVOKED,
    VERSION_ACTIVE,
    VERSION_DEPRECATED,
    VERSION_INACTIVE,
    VERSION_REVOKED,
)
from marketplace.manifest import AgentManifest, ManifestValidationError, validate_manifest, parse_manifest
from marketplace.skills import SkillManifest, SkillRegistry, SkillSearchQuery, parse_skill
from marketplace.deps import DependencyResolver, Dependency, parse_dependencies, satisfies
from marketplace.permissions import PermissionService, PermissionDecision
from marketplace.sandbox_provider import (
    SandboxProvider,
    LocalProcessSandbox,
    DockerSandbox,
    KubernetesSandbox,
    get_sandbox_provider,
    SandboxSpec,
    SandboxResult,
)

__all__ = [
    "CATALOG",
    "DEFAULT_TENANT_ID",
    "MarketplaceService",
    "AgentManifest",
    "ManifestValidationError",
    "validate_manifest",
    "parse_manifest",
    "SkillManifest",
    "SkillRegistry",
    "SkillSearchQuery",
    "parse_skill",
    "DependencyResolver",
    "Dependency",
    "parse_dependencies",
    "satisfies",
    "PermissionService",
    "PermissionDecision",
    "SandboxProvider",
    "LocalProcessSandbox",
    "DockerSandbox",
    "KubernetesSandbox",
    "get_sandbox_provider",
    "SandboxSpec",
    "SandboxResult",
    "PKG_DRAFT",
    "PKG_PUBLISHED",
    "PKG_DEPRECATED",
    "PKG_REVOKED",
    "VERSION_ACTIVE",
    "VERSION_INACTIVE",
    "VERSION_DEPRECATED",
    "VERSION_REVOKED",
]
