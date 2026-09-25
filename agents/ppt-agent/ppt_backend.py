"""PPT backend router: auto → DeepPresenter → research-backed stub."""

from __future__ import annotations

import base64
import os
import re
from typing import Any

from deeppresenter_client import deeppresenter_generate, last_error
from stub_pptx import build_stub_pptx, has_usable_research

PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)

_NO_RESEARCH_RE = re.compile(
    r"no relevant results|status:\s*no_relevant_results|上游检索无可用|"
    r"refusing to forward search-engine",
    flags=re.I,
)


def _mode() -> str:
    return (os.getenv("PPT_MODE") or "auto").strip().lower()


def _require_research() -> bool:
    return (os.getenv("PPT_REQUIRE_RESEARCH") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def run_ppt(query: str) -> dict[str, Any]:
    mode = _mode()
    q = (query or "").strip()
    tried: list[str] = []
    raw: bytes | None = None
    meta: dict[str, Any] = {}

    if _require_research() and (
        _NO_RESEARCH_RE.search(q) or not has_usable_research(q)
    ):
        return {
            "query": q,
            "source": "none",
            "status": "insufficient_research",
            "confidence": 0.0,
            "tried": tried,
            "error": "upstream search has no usable research; refusing stub PPT",
            "files": {},
            "content": (
                "PPT generation blocked: no relevant upstream research. "
                "Fix search results (or set PPT_REQUIRE_RESEARCH=false) before retrying."
            ),
        }

    if mode in {"auto", "deeppresenter", "pptagent"}:
        tried.append("deeppresenter")
        result = deeppresenter_generate(q)
        if result is not None:
            raw, meta = result
        elif mode == "deeppresenter":
            return {
                "query": q,
                "source": "error",
                "status": "error",
                "confidence": 0.0,
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
            "status": "error",
            "confidence": 0.0,
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
        "status": "ok",
        "confidence": 0.7 if source != "stub" else 0.45,
        "tried": tried,
        "slide_count": slide_count,
        "format": "pptx",
        "note": meta.get("note"),
        "topic": meta.get("topic"),
        "content": summary,
        "files": {
            "deck.pptx": {
                "encoding": "base64",
                "content": b64,
                "mime": PPTX_MIME,
            }
        },
    }
