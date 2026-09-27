#!/usr/bin/env python3
"""Minimal long-running plugin used by aop-node smoke tests."""

from __future__ import annotations

import sys
import time

print("aop-node-echo-ok", flush=True)
n = 0
while True:
    time.sleep(30)
    n += 1
    print(f"echo-heartbeat n={n}", flush=True)
    if n > 10_000:
        sys.exit(0)
