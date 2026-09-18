#!/usr/bin/env python3
"""Phase 14 smoke: pub/sub fan-out tests (+ full suite if Redis/PG up)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        str(ROOT / "tests" / "test_pubsub_fanout.py"),
        str(ROOT / "tests"),
    ]
    print(" ".join(cmd))
    return subprocess.call(cmd, cwd=str(ROOT))


if __name__ == "__main__":
    raise SystemExit(main())
