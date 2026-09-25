#!/usr/bin/env python3
"""Phase 11 smoke: smart router preview + HITL approve/reject APIs."""

from __future__ import annotations

import sys

import httpx

GATEWAY = "http://127.0.0.1:8080"
ORCH = "http://127.0.0.1:8090"


def main() -> int:
    print("[1/4] Health ...")
    for name, url in [("gateway", f"{GATEWAY}/health"), ("orchestrator", f"{ORCH}/health")]:
        r = httpx.get(url, timeout=5)
        print(f"      {name}: {r.status_code} {r.json()}")
        if r.status_code != 200:
            return 1

    print("[2/4] GET /v1/router/preview?skill=web-research ...")
    prev = httpx.get(f"{GATEWAY}/v1/router/preview", params={"skill": "web-research"}, timeout=10)
    print(f"      status={prev.status_code}")
    if prev.status_code != 200:
        print(prev.text)
        return 1
    body = prev.json()
    print(
        f"      smart={body.get('smart')} candidates={len(body.get('candidates') or [])} "
        f"selected={body.get('selected')}"
    )

    print("[3/4] GET /v1/stats/agents ...")
    stats = httpx.get(f"{GATEWAY}/v1/stats/agents", timeout=10)
    print(f"      status={stats.status_code} agents={len((stats.json() or {}).get('agents') or [])}")
    if stats.status_code != 200:
        print(stats.text)
        return 1

    print("[4/4] HITL endpoints exist (approve/reject on missing task → 404) ...")
    fake = "00000000-0000-0000-0000-000000000099"
    a = httpx.post(f"{GATEWAY}/v1/tasks/{fake}/approve", json={}, timeout=10)
    rj = httpx.post(f"{GATEWAY}/v1/tasks/{fake}/reject", json={"reason": "smoke"}, timeout=10)
    print(f"      approve={a.status_code} reject={rj.status_code}")
    if a.status_code != 404 or rj.status_code != 404:
        print("      expected 404 for unknown task")
        return 1

    print("PHASE11 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
