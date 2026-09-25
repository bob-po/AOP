"""Harness package — A2A shell + pluggable execution kernels."""

from __future__ import annotations

from .protocol import (
    SCHEMA_VERSION,
    EventCallback,
    HarnessEvent,
    HarnessEventType,
    HarnessResult,
    HarnessRunner,
    HarnessStatus,
    TokenUsage,
)
from .events import (
    apply_event,
    data_part,
    finalize_task,
    new_working_task,
    text_part,
    to_execution_event_dict,
    utc_now,
)
from .cost import attach_usage, estimate_cost, report_usage_to_os
from .process import ManagedProcess, ProcessSupervisor
from .adapter import create_harness_app, load_agent_card

# Re-export runners for convenience
from .runners import (
    ClaudeCliRunner,
    DeepSeekHarnessRunner,
    PiCliRunner,
    create_runner,
)

__all__ = [
    "SCHEMA_VERSION",
    "EventCallback",
    "HarnessEvent",
    "HarnessEventType",
    "HarnessResult",
    "HarnessRunner",
    "HarnessStatus",
    "TokenUsage",
    "apply_event",
    "data_part",
    "finalize_task",
    "new_working_task",
    "text_part",
    "to_execution_event_dict",
    "utc_now",
    "attach_usage",
    "estimate_cost",
    "report_usage_to_os",
    "ManagedProcess",
    "ProcessSupervisor",
    "create_harness_app",
    "load_agent_card",
    "ClaudeCliRunner",
    "PiCliRunner",
    "DeepSeekHarnessRunner",
    "create_runner",
]
