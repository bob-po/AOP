#!/usr/bin/env python3
"""Phase 34 smoke: tenant egress policy + migrate 012."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORCH = ROOT / "apps" / "orchestrator"
MIGRATE = ROOT / "infrastructure" / "postgres" / "migrate.py"


def main() -> int:
    print("[1/3] migrate list includes 012")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_migrate.py", "-k", "list_migrations"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/3] apply migrate")
    subprocess.call([sys.executable, str(MIGRATE)])

    print("[3/3] egress unit tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_egress.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc
    print("PHASE34 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
