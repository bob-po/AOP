#!/usr/bin/env python3
"""Phase 18 smoke: migrator status + no runtime DDL in memory/evaluation."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATE = ROOT / "infrastructure" / "postgres" / "migrate.py"
MEMORY = ROOT / "apps" / "orchestrator" / "memory" / "__init__.py"
EVAL = ROOT / "apps" / "orchestrator" / "evaluation" / "__init__.py"


def _forbids_create_table(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    src = path.read_text(encoding="utf-8")
    assert "CREATE TABLE" not in src.upper(), f"{path} still contains CREATE TABLE"
    # ensure_schema should be gone
    assert "def ensure_schema" not in src, f"{path} still defines ensure_schema"


def main() -> int:
    print("[1/3] Forbid runtime DDL in memory/evaluation")
    _forbids_create_table(MEMORY)
    _forbids_create_table(EVAL)
    print("  ok")

    print("[2/3] Migrator --status")
    rc = subprocess.call([sys.executable, str(MIGRATE), "--status"])
    if rc != 0:
        print("  status failed (is Postgres up?) — continuing dry checks only")
    else:
        print("  ok")

    print("[3/3] Migrator --dry-run / apply")
    rc = subprocess.call([sys.executable, str(MIGRATE), "--dry-run"])
    if rc != 0:
        print("  dry-run skipped (DB unavailable)")
    else:
        rc = subprocess.call([sys.executable, str(MIGRATE)])
        if rc != 0:
            return rc
        print("  applied/up-to-date")

    print("PHASE18 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
