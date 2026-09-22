"""PPT backend router: auto → DeepPresenter → stub."""

from __future__ import annotations

import base64
import os
from typing import Any

from deeppresenter_client import deeppresenter_generate, last_error
from stub_pptx import build_stub_pptx

PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


def _mode() -> str:
    return (os.getenv("PPT_MODE") or "auto").strip().lower()


def run_ppt(query: str) -> dict[str, Any]:
    mode = _mode()
    q = (query or "").strip()
    tried: list[str] = []
    raw: bytes | None = None
    meta: dict[str, Any] = {}

    if mode in {"auto", "deeppresenter", "pptagent"}:
        tried.append("deeppresenter")
        result = deeppresenter_generate(q)
        if result is not None:
            raw, meta = result
        elif mode == "deeppresenter":
            return {
                "query": q,
                "source": "error",
                "tried": tried,
                "error": last_error() or "DeepPresenter unavailable",
                "files": {},
                "content": f"DeepPresenter failed: {last_error()}",
            }

    if raw is None and mode in {"auto", "stub", ""}:
        tried.append("stub")
        raw, meta = build_stub_pptx(q)

    if raw is None:
        return {
            "query": q,
            "source": "error",
            "tried": tried,
            "error": last_error() or "no backend produced pptx",
            "files": {},
            "content": "PPT generation failed",
        }

    b64 = base64.b64encode(raw).decode("ascii")
    slide_count = meta.get("slide_count")
    source = meta.get("source") or "unknown"
    summary = f"PPTX via {source}"
    if slide_count:
        summary += f" ({slide_count} slides)"
    return {
        "query": q,
        "source": source,
        "tried": tried,
        "slide_count": slide_count,
        "format": "pptx",
        "note": meta.get("note"),
        "content": summary,
        "files": {
            "deck.pptx": {
                "encoding": "base64",
                "content": b64,
                "mime": PPTX_MIME,
            }
        },
    }
