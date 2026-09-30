"""Shared aop-node plugin entry for harness profiles.

``plugin.toml`` sets ``HARNESS_PROFILE`` / ``PORT`` / ``AGENT_ID``. This script
marks the process as node-managed so the harness does **not** run its own OS
heartbeat (aopd owns edge heartbeats).
"""

from __future__ import annotations

import os
from pathlib import Path

# workdir in plugin.toml is the plugin directory (e.g. plugins/claude-code).
plugin_dir = Path(os.environ.get("AOP_PLUGIN_DIR") or os.getcwd()).resolve()
os.environ["AOP_PLUGIN_DIR"] = str(plugin_dir)

# Edge SoT: supervisor registers + heartbeats; children only serve A2A.
os.environ["AOP_NODE_MANAGED"] = "1"
os.environ["HARNESS_HEARTBEAT"] = "0"

from launch import main  # noqa: E402

if __name__ == "__main__":
    main()
