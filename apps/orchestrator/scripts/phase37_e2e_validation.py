#!/usr/bin/env python3
"""Deprecated name — forwards to ``scripts/e2e_harness_validation.py``."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[3] / "scripts" / "e2e_harness_validation.py"


def main() -> int:
    print(f"NOTE: prefer `python {TARGET}` (non-phase name).")
    if not TARGET.is_file():
        print(f"missing {TARGET}", file=sys.stderr)
        return 1
    return subprocess.call([sys.executable, str(TARGET), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
