#!/usr/bin/env python3
"""Phase 32 smoke: webhook unit tests + migrate 010."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORCH = ROOT / "apps" / "orchestrator"
MIGRATE = ROOT / "infrastructure" / "postgres" / "migrate.py"
GATEWAY = ROOT / "apps" / "gateway"


def main() -> int:
    print("[1/3] migrate list includes 010")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_migrate.py", "-k", "list_migrations"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/3] apply migrate (optional)")
    subprocess.call([sys.executable, str(MIGRATE)])

    print("[3/3] webhook unit tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_billing_webhook.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[bonus] go test httpapi")
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["GOPROXY"] = env.get("GOPROXY") or "https://goproxy.cn,direct"
    subprocess.call(
        ["go", "test", "./internal/httpapi/", "-count=1"],
        cwd=str(GATEWAY),
        env=env,
    )
    print("PHASE32 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
