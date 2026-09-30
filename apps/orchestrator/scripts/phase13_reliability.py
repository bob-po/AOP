#!/usr/bin/env python3
"""Deprecated alias — use ``pytest`` directly or ``scripts/e2e_harness_validation.py``.

Kept so old docs / muscle memory that run ``phase13_reliability.py`` still work.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    print("NOTE: phase13 is a thin pytest wrapper. Prefer: pytest -q apps/orchestrator/tests")
    cmd = [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")]
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
