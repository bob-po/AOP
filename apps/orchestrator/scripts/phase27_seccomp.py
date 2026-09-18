#!/usr/bin/env python3
"""Phase 27 smoke: seccomp profiles + high-risk sandbox + code AST tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1]


def main() -> int:
    print("[1/2] seccomp + high-risk policy")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_seccomp_profiles.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/2] code-agent AST sandbox")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_code_agent_safe.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("PHASE27 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
