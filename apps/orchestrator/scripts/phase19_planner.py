#!/usr/bin/env python3
"""Deprecated alias — prefer ``pytest -q tests/test_planner*.py``.

Kept for docs that still reference phase19.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1]


def main() -> int:
    print("NOTE: phase19 is a thin pytest wrapper. Prefer: pytest -q tests/test_planner*")
    rc = subprocess.call(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_planner_v2.py",
            "tests/test_planner.py",
        ],
        cwd=str(ORCH),
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
