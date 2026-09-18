"""Phase 29: browser browse backends (stub + mode resolution)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "agents" / "browser-agent"))

from browse import (  # noqa: E402
    browse_stub,
    egress_allowed,
    extract_url,
    resolve_backend,
    run_browse,
)


def test_extract_url():
    assert extract_url("see https://example.com/path now") == "https://example.com/path"
    assert extract_url("no url here") == ""


def test_egress_allowlist(monkeypatch):
    monkeypatch.setenv("BROWSER_EGRESS_ALLOWLIST", "example.com,*.wikipedia.org")
    assert egress_allowed("https://example.com/")
    assert egress_allowed("https://en.wikipedia.org/wiki/A")
    assert not egress_allowed("https://evil.test/")


def test_resolve_backend_stub(monkeypatch):
    monkeypatch.setenv("BROWSER_MODE", "stub")
    assert resolve_backend() == "stub"


def test_run_browse_stub(monkeypatch):
    monkeypatch.setenv("BROWSER_MODE", "stub")
    monkeypatch.delenv("BROWSER_EGRESS_ALLOWLIST", raising=False)
    out = run_browse("Open https://example.com please")
    assert out["ok"] is True
    assert out["backend"] == "stub"
    assert out["host"] == "example.com"


def test_run_browse_blocks_egress(monkeypatch):
    monkeypatch.setenv("BROWSER_MODE", "stub")
    monkeypatch.setenv("BROWSER_EGRESS_ALLOWLIST", "allowed.test")
    out = run_browse("https://denied.test/")
    assert out["ok"] is False
    assert "allowlist" in out["error"]


def test_playwright_fallback_on_error(monkeypatch):
    monkeypatch.setenv("BROWSER_MODE", "playwright")
    with (
        patch("browse.playwright_available", return_value=True),
        patch("browse.resolve_backend", return_value="playwright"),
        patch("browse.browse_playwright", side_effect=RuntimeError("no browser")),
    ):
        out = run_browse("https://example.com/")
    assert out["ok"] is True
    assert out["backend"] == "stub"
    assert "fallback_error" in out


def test_browse_stub_shape():
    out = browse_stub("https://example.com/")
    assert out["title"].startswith("[stub]")
    assert out["screenshot_b64"] is None
