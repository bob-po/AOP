"""Phase 27: high-risk skill routing + seccomp profile validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sandbox import SandboxViolation, guard_call
from sandbox.profiles import (
    check_high_risk_endpoint,
    profile_for_skill,
    validate_profiles,
)


def test_seccomp_profiles_parse():
    names = validate_profiles()
    assert "agent-hardened.json" in names
    assert "code-agent.json" in names


def test_profile_for_skill():
    assert profile_for_skill("code-execution") == "code-agent.json"
    assert profile_for_skill("web-research") == "agent-hardened.json"


def test_high_risk_requires_dedicated_host():
    with patch.dict(os.environ, {"AGENT_ALLOW_HIGH_RISK": "1"}, clear=False):
        check_high_risk_endpoint("code-execution", "http://claude-code:8011/")
        check_high_risk_endpoint("code-execution", "http://deepseek-harness:8012/")
        check_high_risk_endpoint("code-execution", "http://pi:8013/")
        check_high_risk_endpoint("code-execution", "http://127.0.0.1:8011/")
        with pytest.raises(SandboxViolation, match="requires host"):
            check_high_risk_endpoint("code-execution", "http://evil.example:8011/")


def test_high_risk_gate_off():
    with patch.dict(os.environ, {"AGENT_ALLOW_HIGH_RISK": "0"}, clear=False):
        with pytest.raises(SandboxViolation, match="disabled"):
            check_high_risk_endpoint("code-execution", "http://claude-code:8011/")


def test_guard_call_high_risk_ok():
    with patch.dict(
        os.environ,
        {"AGENT_SANDBOX": "1", "AGENT_ALLOW_HIGH_RISK": "1"},
        clear=False,
    ):
        q, t = guard_call(
            endpoint="http://claude-code:8011/",
            skill="code-execution",
            query="1+1",
        )
        assert q == "1+1"
        assert t > 0
