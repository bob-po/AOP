#!/usr/bin/env python3
"""Phase 17 smoke: metrics helpers + gateway LB health tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORCH = ROOT / "apps" / "orchestrator"
GATEWAY = ROOT / "apps" / "gateway"


def main() -> int:
    print("[1/2] Orchestrator metrics unit tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_observability_metrics.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/2] Gateway health-aware LB tests")
    env = os.environ.copy()
    env["GOPROXY"] = env.get("GOPROXY") or "https://goproxy.cn,direct"
    rc = subprocess.call(
        ["go", "test", "./internal/httpapi/", "-count=1", "-run", "LoadBalanced"],
        cwd=str(GATEWAY),
        env=env,
    )
    if rc != 0:
        return rc
    print("PHASE17 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
