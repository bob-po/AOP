"""Tests for virtual-agent zip bundles + Claude-style install scripts."""

from __future__ import annotations

import io
import zipfile

import pytest

from marketplace.bundle import (
    BundleError,
    attach_bundle_meta,
    build_agent_bundle,
    harness_for_profile,
    install_urls,
    render_install_ps1,
    render_install_sh,
    resolve_package_meta,
)
from marketplace.service import CATALOG


def test_harness_for_profile():
    assert harness_for_profile("claude-coder") == "claude_cli"
    assert harness_for_profile("pi-researcher") == "pi_cli"
    assert harness_for_profile("deepseek-coder") == "deepseek"


def test_resolve_by_agent_key():
    meta = resolve_package_meta("claude-coder", CATALOG)
    assert meta["package_id"] == "pkg-claude-coder"
    assert meta["profile"] == "claude-coder"
    assert meta["harness"] == "claude_cli"
    assert meta["default_port"] == 8011


def test_install_urls_claude_style():
    urls = install_urls("pkg-claude-coder", base_url="http://os:8000", profile="claude-coder")
    assert urls["windows"] == "irm http://os:8000/install/claude-coder.ps1 | iex"
    assert urls["unix"] == "curl -fsSL http://os:8000/install/claude-coder.sh | bash"
    assert "pkg-claude-coder/install.ps1" in urls["windows_full"]


def test_attach_bundle_meta():
    pkg = attach_bundle_meta(CATALOG[0], base_url="http://127.0.0.1:8000", catalog=CATALOG)
    assert pkg["bundle"] is True
    assert pkg["install"]["windows"].startswith("irm ")
    assert "/download" in pkg["download_url"]


def test_render_install_ps1_embeds_download():
    script, meta = render_install_ps1(
        "pkg-pi-coder",
        base_url="http://aop.example:8000",
        catalog=CATALOG,
    )
    assert meta["profile"] == "pi-coder"
    assert "Invoke-WebRequest" in script
    assert 'BaseUrl = \'http://aop.example:8000\'' in script
    assert "$PackageId = 'pkg-pi-coder'" in script
    assert "/v1/marketplace/agents/$PackageId/download" in script
    assert "Expand-Archive" in script
    assert "pip install -r requirements.txt" in script
    assert "irm $BaseUrl/v1/marketplace/agents/$PackageId/install.ps1 | iex" in script


def test_render_install_sh_embeds_download():
    script, meta = render_install_sh(
        "deepseek-researcher",
        base_url="http://aop.example:8000",
        catalog=CATALOG,
    )
    assert meta["package_id"] == "pkg-deepseek-researcher"
    assert script.startswith("#!/usr/bin/env bash")
    assert "curl -fsSL" in script
    assert "/download" in script
    assert "venv" in script


def test_build_agent_bundle_zip():
    data, meta = build_agent_bundle("pkg-claude-coder", catalog=CATALOG)
    assert meta["filename"].endswith(".zip")
    assert meta["size_bytes"] == len(data)
    assert len(data) > 1000
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
    assert "claude-coder/agent.py" in names
    assert "claude-coder/agent-card.json" in names
    assert "claude-coder/system.md" in names
    assert "claude-coder/requirements.txt" in names
    assert "claude-coder/scripts/register.py" in names
    assert "claude-coder/bundle.json" in names
    assert any(n.startswith("claude-coder/vendor/agent-runtime/") for n in names)
    assert any(n.startswith("claude-coder/vendor/llm-provider/") for n in names)


def test_build_unknown_package():
    with pytest.raises(BundleError):
        build_agent_bundle("pkg-does-not-exist", catalog=CATALOG)
