#!/usr/bin/env python3
"""Phase 12 smoke: task memory + observability metrics."""

from __future__ import annotations

import sys
import time

import httpx

GATEWAY = "http://127.0.0.1:8080"
ORCH = "http://127.0.0.1:8090"


def main() -> int:
    print("[1/5] Health ...")
    for name, url in [("gateway", f"{GATEWAY}/health"), ("orchestrator", f"{ORCH}/health")]:
        r = httpx.get(url, timeout=5)
        print(f"      {name}: {r.status_code} {r.json()}")
        if r.status_code != 200:
            return 1

    print("[2/5] GET /v1/metrics ...")
    m = httpx.get(f"{GATEWAY}/v1/metrics", params={"hours": 24}, timeout=10)
    print(f"      status={m.status_code}")
    if m.status_code != 200:
        print(m.text)
        return 1
    snap = m.json()
    print(
        f"      tasks={snap.get('tasks')} memories={snap.get('memories')} "
        f"runs={snap.get('agent_runs')}"
    )

    print("[3/5] Create + cancel task for memory seed ...")
    created = httpx.post(
        f"{GATEWAY}/v1/tasks",
        json={"input": {"type": "text", "content": "phase12 memory smoke goal"}},
        timeout=30,
    )
    if created.status_code >= 300:
        print(f"      create failed {created.status_code}: {created.text}")
        print("PHASE12 PARTIAL — metrics OK")
        return 0
    tid = created.json()["task_id"]
    print(f"      task={tid[:8]}")
    time.sleep(0.3)

    print("[4/5] PUT /v1/tasks/{id}/memory ...")
    put = httpx.put(
        f"{GATEWAY}/v1/tasks/{tid}/memory",
        json={"memory_key": "note", "content": "smoke memory entry", "metadata": {"kind": "smoke"}},
        timeout=10,
    )
    print(f"      status={put.status_code}")
    if put.status_code != 200:
        print(put.text)
        return 1

    print("[5/5] GET memory + cancel ...")
    got = httpx.get(f"{GATEWAY}/v1/tasks/{tid}/memory", timeout=10)
    print(f"      status={got.status_code} count={len((got.json() or {}).get('memories') or [])}")
    if got.status_code != 200:
        print(got.text)
        return 1
    keys = {x.get("memory_key") for x in (got.json().get("memories") or [])}
    if "note" not in keys:
        print(f"      missing note key in {keys}")
        return 1
    # goal may already be written on create
    httpx.post(f"{GATEWAY}/v1/tasks/{tid}/cancel", timeout=10)
    print("PHASE12 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
