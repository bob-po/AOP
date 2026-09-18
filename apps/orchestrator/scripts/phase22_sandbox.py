#!/usr/bin/env python3
"""Phase 22 smoke: agent sandbox policy tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1]


def main() -> int:
    print("[1/1] Sandbox policy + endpoint normalize tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_sandbox.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc
    print("PHASE22 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
