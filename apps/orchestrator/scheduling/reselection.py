"""Phase 5.8 — Failure classification + Agent reselection."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional


class FailureClass(str, Enum):
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    TIMEOUT = "TIMEOUT"
    CAPABILITY_FAILURE = "CAPABILITY_FAILURE"
    RESOURCE_FAILURE = "RESOURCE_FAILURE"
    POLICY_DENIED = "POLICY_DENIED"
    AGENT_OFFLINE = "AGENT_OFFLINE"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"
    UNKNOWN = "UNKNOWN"


def classify_failure(
    *,
    error_code: str | None = None,
    error: str | None = None,
    agent_state: str | None = None,
    http_status: int | None = None,
) -> FailureClass:
    code = (error_code or "").upper()
    msg = (error or "").lower()
    state = (agent_state or "").upper()

    if state in {"OFFLINE", "DRAINING"} or code in {"AGENT_OFFLINE", "OFFLINE"}:
        return FailureClass.AGENT_OFFLINE
    if code in {"TIMEOUT", "DEADLINE_EXCEEDED"} or "timeout" in msg:
        return FailureClass.TIMEOUT
    if code in {"POLICY_DENIED", "GOVERNANCE", "BUDGET"} or "policy" in msg or "denied" in msg:
        return FailureClass.POLICY_DENIED
    if code in {"CAPACITY", "RESOURCE", "OOM"} or "capacity" in msg or "resource" in msg:
        return FailureClass.RESOURCE_FAILURE
    if code in {"CAPABILITY", "UNSUPPORTED"} or "capability" in msg or "unsupported" in msg:
        return FailureClass.CAPABILITY_FAILURE
    if code in {"INVALID_INPUT", "VALIDATION", "PERMANENT"} or "invalid" in msg:
        return FailureClass.PERMANENT_FAILURE
    if http_status and 500 <= http_status < 600:
        return FailureClass.TRANSIENT_FAILURE
    if code in {"RECOVER", "TRANSIENT", "UNAVAILABLE"}:
        return FailureClass.TRANSIENT_FAILURE
    return FailureClass.UNKNOWN


def should_reselect_agent(klass: FailureClass) -> bool:
    return klass in {
        FailureClass.TIMEOUT,
        FailureClass.AGENT_OFFLINE,
        FailureClass.TRANSIENT_FAILURE,
        FailureClass.RESOURCE_FAILURE,
        FailureClass.CAPABILITY_FAILURE,
    }


def should_retry_same_agent(klass: FailureClass) -> bool:
    return klass in {
        FailureClass.TRANSIENT_FAILURE,
        FailureClass.TIMEOUT,
        FailureClass.RESOURCE_FAILURE,
    }


def should_abort(klass: FailureClass) -> bool:
    return klass in {
        FailureClass.POLICY_DENIED,
        FailureClass.PERMANENT_FAILURE,
    }


def plan_recovery(
    klass: FailureClass,
    *,
    failed_agent_id: str | None = None,
    exclude_agent_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Decide retry / reselect / abort without breaking lineage identity."""
    excludes = list(exclude_agent_ids or [])
    if failed_agent_id and failed_agent_id not in excludes:
        excludes.append(failed_agent_id)

    if should_abort(klass):
        return {
            "action": "abort",
            "class": klass.value,
            "reselect": False,
            "exclude_agent_ids": excludes,
            "reason": "non-retryable failure class",
        }
    if should_reselect_agent(klass):
        return {
            "action": "reselect",
            "class": klass.value,
            "reselect": True,
            "exclude_agent_ids": excludes,
            "retry_same": should_retry_same_agent(klass),
        }
    return {
        "action": "retry_same",
        "class": klass.value,
        "reselect": False,
        "exclude_agent_ids": excludes,
        "retry_same": True,
    }


__all__ = [
    "FailureClass",
    "classify_failure",
    "should_reselect_agent",
    "should_retry_same_agent",
    "should_abort",
    "plan_recovery",
]
