#!/usr/bin/env python3
"""Phase 24 smoke: audit migration + gateway auth package tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = ROOT / "apps" / "gateway"
MIGRATE = ROOT / "infrastructure" / "postgres" / "migrate.py"
ORCH = ROOT / "apps" / "orchestrator"


def main() -> int:
    print("[1/3] migrate 005")
    subprocess.call([sys.executable, str(MIGRATE)])

    print("[2/3] test_migrate includes 005")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_migrate.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[3/3] go test auth")
    env = os.environ.copy()
    env["GOPROXY"] = env.get("GOPROXY") or "https://goproxy.cn,direct"
    rc = subprocess.call(
        ["go", "test", "./internal/auth/", "./internal/httpapi/", "-count=1"],
        cwd=str(GATEWAY),
        env=env,
    )
    if rc != 0:
        return rc
    print("PHASE24 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
