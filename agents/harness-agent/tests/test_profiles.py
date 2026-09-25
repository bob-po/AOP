"""Profile card loading for harness virtual agents."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"

EXPECTED = {
    "claude-coder": {"code-execution", "code-assist"},
    "claude-researcher": {"web-research", "research-summarize", "web-search"},
    "pi-coder": {"code-execution", "code-assist"},
    "pi-researcher": {"web-research", "research-summarize", "web-search"},
    "deepseek-coder": {"code-execution", "code-assist"},
    "deepseek-researcher": {"web-research", "research-summarize", "web-search"},
}


def test_all_profiles_load():
    for name, skills in EXPECTED.items():
        card = json.loads((PROFILES / name / "agent-card.json").read_text(encoding="utf-8"))
        ids = {s["id"] for s in card["skills"]}
        assert ids == skills, name
        assert (PROFILES / name / "system.md").exists()


def test_only_harness_agent_dir_exists():
    agents_root = ROOT.parent
    dirs = {p.name for p in agents_root.iterdir() if p.is_dir() and not p.name.startswith(".")}
    assert dirs == {"harness-agent"} or dirs <= {"harness-agent", ".pytest_cache"}
    assert "harness-agent" in dirs
    assert "search-agent" not in dirs
