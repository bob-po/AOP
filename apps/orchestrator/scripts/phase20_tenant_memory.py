#!/usr/bin/env python3
"""Phase 20 smoke: tenant memory TF-IDF + optional DB promote/search."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1]
ROOT = ORCH.parents[1]
MIGRATE = ROOT / "infrastructure" / "postgres" / "migrate.py"


def main() -> int:
    print("[1/3] TF-IDF unit tests")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_tenant_memory.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc

    print("[2/3] Apply migration 004 (if Postgres up)")
    rc = subprocess.call([sys.executable, str(MIGRATE)])
    if rc != 0:
        print("  migrate skipped/failed — unit tests only")
        print("PHASE20 OK (partial)")
        return 0

    print("[3/3] put_tenant + search_tenant roundtrip")
    sys.path.insert(0, str(ORCH))
    from memory import MemoryService

    mem = MemoryService()
    key = f"smoke:{uuid.uuid4().hex[:8]}"
    mem.put_tenant(
        key,
        "Phase20 smoke: cross-task AI orchestration memory for agent control plane",
        title="AI orchestration note",
        metadata={"kind": "smoke"},
    )
    hits = mem.search_tenant("AI orchestration agent", top_k=3)
    assert any(h.get("memory_key") == key for h in hits), hits
    mem.delete_tenant(key)
    print("  ok")
    print("PHASE20 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
