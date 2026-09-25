"""Profile card loading for harness virtual agents (unified products)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"

EXPECTED = {"claude-code", "deepseek-harness", "pi"}


def test_all_profiles_load_without_skills():
    assert {p.name for p in PROFILES.iterdir() if p.is_dir()} == EXPECTED
    for name in EXPECTED:
        card = json.loads((PROFILES / name / "agent-card.json").read_text(encoding="utf-8"))
        assert card.get("skills") == [], name
        assert (PROFILES / name / "system.md").exists()


def test_only_harness_agent_dir_exists():
    agents_root = ROOT.parent
    dirs = {p.name for p in agents_root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    assert dirs == {"harness-agent"} or dirs <= {"harness-agent", ".pytest_cache"}
    assert "search-agent" not in dirs
