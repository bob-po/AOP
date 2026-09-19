"""AOP Schema Definitions.

This package provides unified schema definitions for AOP platform components,
including Agent Manifests, Skills, and related structures.
"""

from .agent_manifest import (
    ErrorCode,
    AgentIdentity,
    SkillDefinition,
    AgentCapability,
    AgentRuntime,
    AgentResource,
    AgentMetadata,
    AgentManifest,
)
from .agent_runtime import (
    AgentHealth,
    AgentRuntimeInterface,
    BaseAgentRuntime,
    AgentLifecycleManager,
)
from .agent_errors import (
    AgentError,
    ErrorResponse,
    handle_agent_error,
)

__all__ = [
    "ErrorCode",
    "AgentIdentity",
    "SkillDefinition",
    "AgentCapability",
    "AgentRuntime",
    "AgentResource",
    "AgentMetadata",
    "AgentManifest",
    "AgentHealth",
    "AgentRuntimeInterface",
    "BaseAgentRuntime",
    "AgentLifecycleManager",
    "AgentError",
    "ErrorResponse",
    "handle_agent_error",
]
