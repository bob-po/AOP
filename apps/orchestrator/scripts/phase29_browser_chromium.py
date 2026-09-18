#!/usr/bin/env python3
"""Phase 29 smoke: browser agent browse backends."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1]
AGENT = Path(__file__).resolve().parents[3] / "agents" / "browser-agent"


def main() -> int:
    print("[1/2] browse unit tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_browser_agent.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/2] agent modules import")
    rc = subprocess.call(
        [
            sys.executable,
            "-c",
            "from browse import run_browse, resolve_backend; "
            "assert resolve_backend() in ('stub','playwright'); "
            "r=run_browse('https://example.com'); assert 'ok' in r; print('backend', r.get('backend'))",
        ],
        cwd=str(AGENT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "BROWSER_MODE": "stub"},
    )
    if rc != 0:
        return rc
    print("PHASE29 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
