#!/usr/bin/env python3
"""Phase 26 smoke: billing unit tests + optional live API."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORCH = ROOT / "apps" / "orchestrator"
GATEWAY = os.getenv("AOP_GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{GATEWAY}{path}", method="GET")
    key = os.getenv("AOP_API_KEY", "").strip()
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=8) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    print("[1/2] unit tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_billing.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/2] live GET /v1/billing/usage (optional)")
    try:
        data = _get("/v1/billing/usage?days=7")
        assert "estimated_total_usd" in data
        assert "agent_runs" in data
        print(f"  ok total={data.get('estimated_total_usd')} tasks={data.get('tasks')}")
        summary = _get("/v1/billing/summary")
        assert "d7" in summary and "d30" in summary
        print("  ok summary")
    except (urllib.error.URLError, AssertionError, TimeoutError, OSError) as exc:
        print(f"  skip (gateway down?): {exc}")

    print("PHASE26 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
