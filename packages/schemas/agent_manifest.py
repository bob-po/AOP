"""Agent Manifest Schema Definitions for AOP Reference Agents.

This module provides unified schema definitions for Agent Cards and related structures,
compatible with A2A protocol 0.3.0 and current Agent Card implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """Standardized error codes for A2A agent responses."""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNSUPPORTED_SKILL = "UNSUPPORTED_SKILL"
    AUTH_FAILED = "AUTH_FAILED"
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    TIMEOUT = "TIMEOUT"
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass
class AgentIdentity:
    """Unique agent identification."""

    agent_id: str  # Unique UUID
    agent_key: str  # Human-readable key (e.g., "search-agent")
    name: str  # Display name


@dataclass
class SkillDefinition:
    """Standardized skill definition."""

    id: str  # Skill identifier (e.g., "web-search")
    name: str  # Human-readable name
    description: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    input_modes: list[str] = field(default_factory=lambda: ["text"])
    output_modes: list[str] = field(default_factory=lambda: ["text"])
    requires_approval: bool = False  # HITL flag

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SkillDefinition:
        return cls(
            id=str(raw.get("id") or raw.get("skill_id") or ""),
            name=str(raw.get("name") or ""),
            description=str(raw.get("description") or ""),
            tags=list(raw.get("tags") or []),
            examples=list(raw.get("examples") or []),
            input_modes=list(raw.get("inputModes") or raw.get("input_modes") or ["text"]),
            output_modes=list(raw.get("outputModes") or raw.get("output_modes") or ["text"]),
            requires_approval=bool(raw.get("requires_approval") or raw.get("requiresApproval") or False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "examples": self.examples,
            "inputModes": self.input_modes,
            "outputModes": self.output_modes,
            "requiresApproval": self.requires_approval,
        }


@dataclass
class AgentCapability:
    """Agent capability flags."""

    streaming: bool = False
    push_notifications: bool = False
    file_upload: bool = False
    file_download: bool = False
    web_browsing: bool = False
    code_execution: bool = False

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentCapability:
        return cls(
            streaming=bool(raw.get("streaming") or False),
            push_notifications=bool(raw.get("pushNotifications") or False),
            file_upload=bool(raw.get("fileUpload") or False),
            file_download=bool(raw.get("fileDownload") or False),
            web_browsing=bool(raw.get("webBrowsing") or False),
            code_execution=bool(raw.get("codeExecution") or False),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "streaming": self.streaming,
            "pushNotifications": self.push_notifications,
            "fileUpload": self.file_upload,
            "fileDownload": self.file_download,
            "webBrowsing": self.web_browsing,
            "codeExecution": self.code_execution,
        }


@dataclass
class AgentRuntime:
    """Agent runtime requirements and configuration."""

    framework: str = "fastapi"  # Web framework
    python_version: str = "3.8+"  # Minimum Python version
    memory_mb: int | None = None  # Memory requirement in MB
    timeout_seconds: int = 60  # Default timeout for A2A calls
    max_concurrent_tasks: int | None = None  # Max concurrent task limit
    startup_timeout_seconds: int = 30  # Startup timeout

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentRuntime:
        return cls(
            framework=raw.get("framework") or "fastapi",
            python_version=raw.get("pythonVersion") or "3.8+",
            memory_mb=raw.get("memoryMb"),
            timeout_seconds=int(raw.get("timeoutSeconds") or 60),
            max_concurrent_tasks=raw.get("maxConcurrentTasks"),
            startup_timeout_seconds=int(raw.get("startupTimeoutSeconds") or 30),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "framework": self.framework,
            "pythonVersion": self.python_version,
            "memoryMb": self.memory_mb,
            "timeoutSeconds": self.timeout_seconds,
            "maxConcurrentTasks": self.max_concurrent_tasks,
            "startupTimeoutSeconds": self.startup_timeout_seconds,
        }


@dataclass
class AgentResource:
    """Agent resource requirements."""

    cpu_cores: float | None = None  # CPU cores required
    memory_mb: int | None = None  # Memory in MB
    disk_mb: int | None = None  # Disk in MB
    gpu_required: bool = False  # GPU requirement
    gpu_type: str | None = None  # GPU type (e.g., "T4", "V100")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentResource:
        return cls(
            cpu_cores=raw.get("cpuCores"),
            memory_mb=raw.get("memoryMb"),
            disk_mb=raw.get("diskMb"),
            gpu_required=bool(raw.get("gpuRequired") or False),
            gpu_type=raw.get("gpuType"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpuCores": self.cpu_cores,
            "memoryMb": self.memory_mb,
            "diskMb": self.disk_mb,
            "gpuRequired": self.gpu_required,
            "gpuType": self.gpu_type,
        }


@dataclass
class AgentMetadata:
    """Additional agent metadata."""

    author: str = ""
    license: str = ""
    repository: str = ""
    documentation: str = ""
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentMetadata:
        return cls(
            author=raw.get("author") or "",
            license=raw.get("license") or "",
            repository=raw.get("repository") or "",
            documentation=raw.get("documentation") or "",
            tags=list(raw.get("tags") or []),
            categories=list(raw.get("categories") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "license": self.license,
            "repository": self.repository,
            "documentation": self.documentation,
            "tags": self.tags,
            "categories": self.categories,
        }


@dataclass
class AgentManifest:
    """Unified Agent Manifest compatible with current Agent Cards.

    This schema extends the current Agent Card format with additional fields
    for standardization while maintaining backward compatibility.
    """

    # Core identity (from current Agent Card)
    name: str
    description: str
    url: str
    version: str
    protocol_version: str = "0.3.0"

    # Extended identity
    agent_id: str = ""  # Unique UUID (new)
    agent_key: str = ""  # Human-readable key (new)

    # Capabilities
    capabilities: AgentCapability = field(default_factory=AgentCapability)

    # Skills
    skills: list[SkillDefinition] = field(default_factory=list)

    # I/O modes
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text"])

    # Runtime requirements (new)
    runtime: AgentRuntime = field(default_factory=AgentRuntime)

    # Resource requirements (new)
    resources: AgentResource = field(default_factory=AgentResource)

    # Metadata (new)
    metadata: AgentMetadata = field(default_factory=AgentMetadata)

    # Raw data for compatibility
    raw: dict[str, Any] = field(default_factory=dict)

    def skill_ids(self) -> list[str]:
        """Get list of skill IDs."""
        return [s.id for s in self.skills if s.id]

    def get_skill(self, skill_id: str) -> SkillDefinition | None:
        """Get skill by ID."""
        for skill in self.skills:
            if skill.id == skill_id:
                return skill
        return None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AgentManifest:
        """Create AgentManifest from dictionary (Agent Card JSON)."""
        # Parse skills
        skills = [SkillDefinition.from_dict(s) for s in raw.get("skills", [])]

        # Parse capabilities
        capabilities = AgentCapability.from_dict(raw.get("capabilities") or {})

        # Parse runtime (new field, use defaults if missing)
        runtime = AgentRuntime.from_dict(raw.get("runtime") or {})

        # Parse resources (new field, use defaults if missing)
        resources = AgentResource.from_dict(raw.get("resources") or {})

        # Parse metadata (new field, use defaults if missing)
        metadata = AgentMetadata.from_dict(raw.get("metadata") or {})

        return cls(
            name=raw.get("name") or "",
            description=raw.get("description") or "",
            url=raw.get("url") or "",
            version=raw.get("version") or "0.0.0",
            protocol_version=str(
                raw.get("protocolVersion") or raw.get("protocol_version") or "0.3.0"
            ),
            agent_id=raw.get("agentId") or raw.get("agent_id") or "",
            agent_key=raw.get("agentKey") or raw.get("agent_key") or "",
            capabilities=capabilities,
            skills=skills,
            default_input_modes=list(
                raw.get("defaultInputModes") or raw.get("default_input_modes") or ["text"]
            ),
            default_output_modes=list(
                raw.get("defaultOutputModes") or raw.get("default_output_modes") or ["text"]
            ),
            runtime=runtime,
            resources=resources,
            metadata=metadata,
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert AgentManifest to dictionary (Agent Card JSON format)."""
        result = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "capabilities": self.capabilities.to_dict(),
            "skills": [s.to_dict() for s in self.skills],
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
        }

        # Add new fields if they have values
        if self.agent_id:
            result["agentId"] = self.agent_id
        if self.agent_key:
            result["agentKey"] = self.agent_key
        if self.runtime.framework != "fastapi" or self.runtime.timeout_seconds != 60:
            result["runtime"] = self.runtime.to_dict()
        if self.resources.cpu_cores or self.resources.memory_mb or self.resources.gpu_required:
            result["resources"] = self.resources.to_dict()
        if self.metadata.author or self.metadata.tags:
            result["metadata"] = self.metadata.to_dict()

        return result

    def to_agent_card_dict(self) -> dict[str, Any]:
        """Convert to legacy Agent Card format (backward compatibility)."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "protocolVersion": self.protocol_version,
            "capabilities": self.capabilities.to_dict(),
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
            "skills": [s.to_dict() for s in self.skills],
        }


__all__ = [
    "ErrorCode",
    "AgentIdentity",
    "SkillDefinition",
    "AgentCapability",
    "AgentRuntime",
    "AgentResource",
    "AgentMetadata",
    "AgentManifest",
]
