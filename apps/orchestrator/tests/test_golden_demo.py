"""Golden demo helpers — hermetic, no live Gateway."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "golden_demo", ROOT / "scripts" / "golden_demo.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_console_url_and_task_id():
    assert mod.console_task_url("http://127.0.0.1:3000/", "abc") == (
        "http://127.0.0.1:3000/?task=abc"
    )
    assert mod.task_id_of({"task_id": "t1"}) == "t1"
    assert mod.task_id_of({"id": "t2"}) == "t2"
    assert mod.task_id_of({}) is None


def test_blocked_hint_and_done():
    assert mod.blocked_hint({"can_run": True}) is None
    assert "worker" in (mod.blocked_hint({"can_run": False, "blocking": ["worker"]}) or "")
    assert "Outbox" in (
        mod.blocked_hint({"can_run": False, "hints": ["Outbox down"]}) or ""
    )
    assert mod.demo_done("completed")
    assert mod.demo_done("waiting_for_user")
    assert not mod.demo_done("running")
    assert not mod.demo_done(None)


def test_golden_prompt_matches_command_center():
    assert "Vidu" in mod.GOLDEN_PROMPT
