"""Prompt framing helpers for skill-less harness cards."""

from __future__ import annotations

from agent_runtime.harness.adapter import _skill_id
from agent_runtime.harness.runners._cli_common import (
    compose_cli_prompt,
    skill_label,
    system_with_skill,
)


def test_skill_label_drops_default():
    assert skill_label("") == ""
    assert skill_label("default") == ""
    assert skill_label("none") == ""
    assert skill_label("code-assist") == "code-assist"


def test_compose_cli_prompt_omits_skill_when_empty():
    out = compose_cli_prompt("do thing", system="sys", skill_id="")
    assert "skill=" not in out
    assert "User task:" in out
    assert "do thing" in out


def test_compose_cli_prompt_includes_real_skill():
    out = compose_cli_prompt("do thing", system="sys", skill_id="code-assist")
    assert "User task (skill=code-assist):" in out


def test_system_with_skill_omits_when_empty():
    assert system_with_skill("sys", "") == "sys"
    assert "Active skill" not in system_with_skill("sys", "default")
    assert system_with_skill("sys", "web") == "sys\n\nActive skill: web"


def test_adapter_skill_id_empty_for_skillless_card():
    card = {"name": "Claude Code", "skills": []}
    assert _skill_id({"metadata": {}}, card) == ""
    assert _skill_id({"metadata": {"skillId": "explicit"}}, card) == "explicit"
    assert _skill_id({}, {"skills": [{"id": "web-search"}]}) == "web-search"
