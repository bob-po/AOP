#!/usr/bin/env python3
"""Phase 23 smoke: Gateway RBAC unit tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GATEWAY = ROOT / "apps" / "gateway"


def main() -> int:
    print("[1/1] go test auth RBAC")
    env = os.environ.copy()
    env["GOPROXY"] = env.get("GOPROXY") or "https://goproxy.cn,direct"
    rc = subprocess.call(
        ["go", "test", "./internal/auth/", "-count=1"],
        cwd=str(GATEWAY),
        env=env,
    )
    if rc != 0:
        return rc
    print("PHASE23 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
