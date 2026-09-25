"""Backend falls back to stub when DeepPresenter fails."""

from __future__ import annotations

import base64
import os
from unittest.mock import patch

from ppt_backend import run_ppt


def test_auto_falls_back_to_stub():
    prompt = """User goal: A2A protocol overview
Upstream results (via handoff):

1. Agent2Agent protocol
   https://example.com/a2a
   A2A is an open agent interoperability protocol.

Please continue based on the upstream results.
"""
    with patch.dict(
        os.environ,
        {"PPT_MODE": "auto", "PPT_REQUIRE_RESEARCH": "true"},
        clear=False,
    ):
        with patch("ppt_backend.deeppresenter_generate", return_value=None):
            out = run_ppt(prompt)
    assert out["source"] == "stub"
    assert out["status"] == "ok"
    assert "stub" in out["tried"]
    file = out["files"]["deck.pptx"]
    assert file["encoding"] == "base64"
    raw = base64.b64decode(file["content"])
    assert raw[:2] == b"PK"


def test_blocks_without_research():
    with patch.dict(
        os.environ,
        {"PPT_MODE": "stub", "PPT_REQUIRE_RESEARCH": "true"},
        clear=False,
    ):
        out = run_ppt("生成一份关于 ui2v 的 PPT")
    assert out["status"] == "insufficient_research"
    assert out["files"] == {}


def test_deeppresenter_only_errors():
    prompt = """User goal: deck please
Upstream results (via handoff):

1. Some topic
   https://example.com/topic
   Useful research bullet for the deck.

Please continue based on the upstream results.
"""
    with patch.dict(
        os.environ,
        {"PPT_MODE": "deeppresenter", "PPT_REQUIRE_RESEARCH": "true"},
        clear=False,
    ):
        with patch("ppt_backend.deeppresenter_generate", return_value=None):
            with patch("ppt_backend.last_error", return_value="container down"):
                out = run_ppt(prompt)
    assert out["source"] == "error"
    assert out["files"] == {}
    assert "container down" in (out.get("error") or "")
