#!/usr/bin/env python3
"""Phase 28 smoke: migrate 007 + quota unit tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORCH = ROOT / "apps" / "orchestrator"
MIGRATE = ROOT / "infrastructure" / "postgres" / "migrate.py"


def main() -> int:
    print("[1/3] migrate includes 007")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_migrate.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/3] apply migrate (optional if PG up)")
    subprocess.call([sys.executable, str(MIGRATE)])

    print("[3/3] quota unit tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_quota.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc
    print("PHASE28 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
