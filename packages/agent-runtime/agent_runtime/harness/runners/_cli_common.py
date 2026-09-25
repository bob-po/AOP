"""Shared helpers for CLI harness runners."""

from __future__ import annotations

import asyncio
import os
import shutil
from typing import Any, Optional

from ..events import utc_now
from ..protocol import EventCallback, HarnessEvent, HarnessEventType


def message_text(message: dict[str, Any]) -> str:
    parts = message.get("parts") or []
    texts = [str(p.get("text") or "") for p in parts if p.get("type") == "text"]
    return "\n".join(t for t in texts if t).strip()


def system_prompt_from_message(message: dict[str, Any]) -> str:
    meta = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return str((meta or {}).get("systemPrompt") or "").strip()


def resolve_binary(name_or_path: str) -> Optional[str]:
    if not name_or_path:
        return None
    found = shutil.which(name_or_path)
    if found:
        return found
    if os.path.isfile(name_or_path):
        return name_or_path
    return None


async def emit_event(
    on_event: EventCallback,
    *,
    task_id: str,
    etype: HarnessEventType,
    payload: dict[str, Any],
) -> None:
    ev = HarnessEvent(type=etype, task_id=task_id, timestamp=utc_now(), payload=payload)
    maybe = on_event(ev)
    if asyncio.iscoroutine(maybe):
        await maybe
