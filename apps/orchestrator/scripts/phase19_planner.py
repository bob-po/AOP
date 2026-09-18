#!/usr/bin/env python3
"""Phase 19 smoke: planner v2 unit tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1]


def main() -> int:
    print("[1/1] Planner v2 + legacy heuristic tests")
    rc = subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_planner_v2.py",
            "tests/test_planner_heuristic.py",
            "tests/test_dag.py",
        ],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc
    print("PHASE19 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
