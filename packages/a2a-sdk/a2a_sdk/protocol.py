"""Pinned official A2A protocol baseline for AOP.

Spec source: https://github.com/a2aproject/A2A
Canonical definition: specification/a2a.proto
"""

from __future__ import annotations

# a2aproject/A2A main tip used when this package was aligned.
SPEC_COMMIT = "72b3761bd84c59291da694dcd97cdfc2c010df39"
SPEC_URL = f"https://github.com/a2aproject/A2A/tree/{SPEC_COMMIT}/specification"

# Agent Card ``protocolVersion`` (string on the wire).
PROTOCOL_VERSION = "0.3.0"

# Methods AOP must implement for interop.
METHODS_MUST = frozenset(
    {
        "message/send",
        "tasks/get",
        "tasks/cancel",
    }
)

# Methods AOP should implement (or honestly omit from capabilities).
METHODS_SHOULD = frozenset(
    {
        "message/stream",
    }
)

# Deferred / Later.
METHODS_LATER = frozenset(
    {
        "tasks/resubscribe",
        "tasks/pushNotificationConfig/set",
        "tasks/pushNotificationConfig/get",
        "tasks/pushNotificationConfig/list",
        "tasks/pushNotificationConfig/delete",
        "agent/getAuthenticatedExtendedCard",
    }
)

# Removed AOP-only methods (SDK/client raise; servers return -32601).
METHODS_REMOVED = frozenset(
    {
        "tasks/subscribe",
        "tasks/delegate",
    }
)

# Back-compat alias for importers that still reference the old name.
METHODS_DEPRECATED = METHODS_REMOVED


# Official TaskState string values (JSON binding of proto enum).
TASK_STATES = frozenset(
    {
        "submitted",
        "working",
        "completed",
        "failed",
        "canceled",
        "input-required",
        "rejected",
        "auth-required",
    }
)

TERMINAL_TASK_STATES = frozenset(
    {
        "completed",
        "failed",
        "canceled",
        "rejected",
    }
)
