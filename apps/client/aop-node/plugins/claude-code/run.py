"""aop-node plugin: Claude Code harness agent (:8011)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent
os.environ["AOP_PLUGIN_DIR"] = str(PLUGIN_DIR)
os.environ.setdefault("HARNESS_PROFILE", "claude-code")
os.environ.setdefault("AGENT_ID", "claude-code")
os.environ.setdefault("PORT", "8011")
os.environ.setdefault("AGENT_URL", "http://127.0.0.1:8011/")
os.environ.setdefault("HARNESS_HEARTBEAT", "1")

sys.path.insert(0, str(PLUGIN_DIR.parent / "_harness"))
from launch import main  # noqa: E402

if __name__ == "__main__":
    main()
