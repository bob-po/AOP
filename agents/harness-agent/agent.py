"""Harness Agent — A2A shell + pluggable harness runner.

Select a virtual agent profile via ``HARNESS_PROFILE`` (directory under
``profiles/``). Runner defaults from profile name prefix unless
``HARNESS_RUNNER`` is set:

- ``claude-*`` / ``claude-code`` → Claude Code CLI
- ``pi`` / ``pi-*`` → Pi CLI ``--mode json``
- ``deepseek-*`` / ``dsh-*`` → DeepSeek Harness SDK / dsh / tool_loop
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency). Does not override existing env."""
    if not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        pass


ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "profiles"

# Shared secrets first, then profile-specific overrides.
_load_dotenv(ROOT / ".env")
PROFILE = os.getenv("HARNESS_PROFILE") or os.getenv("AGENT_ID") or "claude-code"
_load_dotenv(PROFILES / PROFILE / ".env")

# Bind card URL to this process's listen port. Parent shells often leak
# AGENT_URL/HARNESS_PROFILE from a previous agent start — do not inherit a
# sibling's URL when PORT is set for this instance.
_port = int(os.getenv("PORT", "8011"))
if "PORT" in os.environ or not (os.getenv("AGENT_URL") or "").strip():
    os.environ["AGENT_URL"] = f"http://127.0.0.1:{_port}/"

PROFILE_DIR = PROFILES / PROFILE
if not PROFILE_DIR.is_dir():
    raise SystemExit(f"Unknown harness profile: {PROFILE!r} (looked in {PROFILES})")

from agent_runtime.harness.adapter import create_harness_app, load_agent_card
from agent_runtime.harness.runners import create_runner

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

    uvicorn.run("agent:app", host="0.0.0.0", port=_port, reload=False)
