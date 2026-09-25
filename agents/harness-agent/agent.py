"""Harness Agent — A2A shell + pluggable harness runner.

Select a virtual agent profile via ``HARNESS_PROFILE`` (directory under
``profiles/``). Runner defaults from profile name prefix unless
``HARNESS_RUNNER`` is set:

- ``claude-*`` → Claude Code CLI (https://github.com/anthropics/claude-code)
- ``pi-*`` → Pi CLI ``--mode json`` (https://github.com/earendil-works/pi)
- ``deepseek-*`` → DeepSeek Harness SDK / dsh / tool_loop
  (https://github.com/deepseek-ai/deepseek-harness)
"""

from __future__ import annotations

import os
from pathlib import Path

from agent_runtime.harness.adapter import create_harness_app, load_agent_card
from agent_runtime.harness.runners import create_runner

ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "profiles"

PROFILE = os.getenv("HARNESS_PROFILE") or os.getenv("AGENT_ID") or "claude-coder"
PROFILE_DIR = PROFILES / PROFILE
if not PROFILE_DIR.is_dir():
    raise SystemExit(f"Unknown harness profile: {PROFILE!r} (looked in {PROFILES})")

CARD_PATH = PROFILE_DIR / "agent-card.json"
SYSTEM_PATH = PROFILE_DIR / "system.md"
SYSTEM_PROMPT = SYSTEM_PATH.read_text(encoding="utf-8") if SYSTEM_PATH.exists() else ""

_card = load_agent_card(CARD_PATH)
AGENT_ID = os.getenv("AGENT_ID") or PROFILE


def _default_runner_for_profile(profile: str) -> str:
    p = profile.lower()
    if p.startswith("pi"):
        return "pi_cli"
    if p.startswith("deepseek") or p.startswith("dsh"):
        return "deepseek"
    return "claude_cli"


_runner_name = os.getenv("HARNESS_RUNNER") or _default_runner_for_profile(PROFILE)
try:
    _runner = create_runner(_runner_name)
except ValueError as exc:
    raise SystemExit(str(exc)) from exc

app = create_harness_app(
    agent_id=AGENT_ID,
    runner=_runner,
    card=_card,
    system_prompt=SYSTEM_PROMPT,
    enable_heartbeat=os.getenv("HARNESS_HEARTBEAT", "1") not in {"0", "false", "off"},
    title=f"AOP {_card.get('name') or AGENT_ID}",
    version=str(_card.get("version") or "0.1.0"),
)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8011"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
