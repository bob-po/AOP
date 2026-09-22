"""Backend falls back to stub when DeepPresenter fails."""

from __future__ import annotations

import base64
import os
from unittest.mock import patch

from ppt_backend import run_ppt


def test_auto_falls_back_to_stub():
    with patch.dict(os.environ, {"PPT_MODE": "auto"}, clear=False):
        with patch("ppt_backend.deeppresenter_generate", return_value=None):
            out = run_ppt("生成一份关于 A2A 的 PPT")
    assert out["source"] == "stub"
    assert "stub" in out["tried"]
    file = out["files"]["deck.pptx"]
    assert file["encoding"] == "base64"
    raw = base64.b64decode(file["content"])
    assert raw[:2] == b"PK"


def test_deeppresenter_only_errors():
    with patch.dict(os.environ, {"PPT_MODE": "deeppresenter"}, clear=False):
        with patch("ppt_backend.deeppresenter_generate", return_value=None):
            with patch("ppt_backend.last_error", return_value="container down"):
                out = run_ppt("deck please")
    assert out["source"] == "error"
    assert out["files"] == {}
    assert "container down" in (out.get("error") or "")
