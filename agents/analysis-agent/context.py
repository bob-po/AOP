"""Prompt parsing + optional LLM synthesis for the analysis/report agents.

The orchestrator's executor composes a downstream agent's input as a single
text blob: the user goal, then an "Upstream results:" section containing one
``### <node_id> (<skill>)`` block per completed upstream node. These helpers
parse that blob back into structured form and — when ``OPENAI_API_KEY`` is set
— route synthesis through an OpenAI-compatible LLM (OpenAI itself, or a
gateway such as new-api). When no key is configured (or the call fails),
callers fall back to deterministic aggregation so the loop keeps working
offline.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any


def parse_composed_query(text: str) -> dict[str, Any]:
    """Return ``{"goal": str, "upstream": {node_id: section_text}}``.

    Handles both the executor-composed prompt and a bare single-node goal.
    """
    text = text or ""
    goal = ""
    m = re.search(r"^User goal:\s*(.+)$", text, re.MULTILINE)
    if m:
        goal = m.group(1).strip()
    if not goal:
        goal = text.strip()

    upstream: dict[str, str] = {}
    header_re = re.compile(r"^###\s+([^\s()]+)\s*\(([^)]*)\)\s*$", re.MULTILINE)
    matches = list(header_re.finditer(text))
    for i, match in enumerate(matches):
        node_id = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        body = re.sub(
            r"^Please continue based on the upstream results\..*$",
            "",
            body,
            flags=re.MULTILINE,
        )
        upstream[node_id] = body.strip()
    return {"goal": goal, "upstream": upstream}


def llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def llm_chat(system: str, user: str, *, json_mode: bool = False) -> str | None:
    """OpenAI-compatible chat completion. Returns content, or None on failure."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": api_key}
        base_url = os.getenv("OPENAI_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        model = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
        create_kwargs: dict[str, Any] = {
            "model": model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            create_kwargs["response_format"] = {"type": "json_object"}
        resp = client.chat.completions.create(**create_kwargs)
        return (resp.choices[0].message.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[llm] chat failed: {exc}")
        return None


def parse_json_lenient(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction (tolerates ```json fences)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:  # noqa: BLE001
            pass
    obj = re.search(r"\{.*\}", text, re.DOTALL)
    if obj:
        try:
            return json.loads(obj.group(0))
        except Exception:  # noqa: BLE001
            return None
    return None


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)]+", text or "")


def format_upstream(upstream: dict[str, str]) -> str:
    """Render upstream sections for an LLM prompt."""
    blocks = []
    for node_id, body in upstream.items():
        if body:
            blocks.append(f"### {node_id}\n{body}")
    return "\n\n".join(blocks)
