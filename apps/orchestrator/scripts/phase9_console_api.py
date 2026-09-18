#!/usr/bin/env python3
"""Phase 9 smoke: list tasks, overview stats, artifacts, cancel."""

from __future__ import annotations

import sys
import time

import httpx

GATEWAY = "http://127.0.0.1:8080"
ORCH = "http://127.0.0.1:8090"


def main() -> int:
    print("[1/5] Health checks ...")
    for name, url in [("gateway", f"{GATEWAY}/health"), ("orchestrator", f"{ORCH}/health")]:
        r = httpx.get(url, timeout=5)
        print(f"      {name}: {r.status_code} {r.json()}")
        if r.status_code != 200:
            return 1

    print("[2/5] GET /v1/stats/overview ...")
    stats = httpx.get(f"{GATEWAY}/v1/stats/overview", timeout=10)
    print(f"      status={stats.status_code}")
    if stats.status_code != 200:
        print(stats.text)
        return 1
    body = stats.json()
    print(
        f"      tasks={body.get('total_tasks')} running={body.get('running')} "
        f"success_rate={body.get('success_rate')} trend_days={len(body.get('trend') or [])}"
    )

    print("[3/5] GET /v1/tasks ...")
    listed = httpx.get(f"{GATEWAY}/v1/tasks?limit=10", timeout=10)
    print(f"      status={listed.status_code}")
    if listed.status_code != 200:
        print(listed.text)
        return 1
    tasks = listed.json().get("tasks") or []
    print(f"      count={len(tasks)}")

    print("[4/5] GET /v1/artifacts ...")
    arts = httpx.get(f"{GATEWAY}/v1/artifacts?limit=20", timeout=15)
    print(f"      status={arts.status_code}")
    if arts.status_code != 200:
        print(arts.text)
        return 1
    print(f"      artifacts={len(arts.json().get('artifacts') or [])}")

    print("[5/5] Cancel flow (create short-lived if needed) ...")
    # Prefer an existing running task; otherwise create one (may fail without agents)
    target = next((t for t in tasks if t.get("status") in ("running", "ready", "planned", "created")), None)
    if not target:
        created = httpx.post(
            f"{GATEWAY}/v1/tasks",
            json={"input": {"type": "text", "content": "phase9 cancel smoke"}},
            timeout=30,
        )
        if created.status_code >= 300:
            print(f"      skip cancel: cannot create task ({created.status_code})")
            print("PHASE9 OK (partial — list/stats/artifacts)")
            return 0
        target = {"task_id": created.json()["task_id"], "status": created.json().get("status")}
        time.sleep(0.5)

    tid = target["task_id"]
    cancelled = httpx.post(f"{GATEWAY}/v1/tasks/{tid}/cancel", timeout=10)
    print(f"      cancel {tid[:8]} -> {cancelled.status_code}")
    if cancelled.status_code != 200:
        print(cancelled.text)
        return 1
    print(f"      status={cancelled.json().get('status')}")

    print("PHASE9 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
