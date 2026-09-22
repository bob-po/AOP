"""Stub PPTX produces a valid OOXML zip."""

from __future__ import annotations

from stub_pptx import build_stub_pptx


def test_stub_pptx_is_zip():
    raw, meta = build_stub_pptx("产品发布会演示文稿")
    assert raw[:2] == b"PK"
    assert meta["source"] == "stub"
    assert meta["slide_count"] >= 1
    assert len(raw) > 1000
