#!/usr/bin/env python3
"""Phase 10 smoke: evaluation APIs + heuristic score on a terminal task."""

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
        phase = (r.json() or {}).get("phase") or ""
        if "10" not in str(phase) and name == "orchestrator":
            print(f"      warn: expected phase 10-evaluation, got {phase!r}")

    print("[2/5] GET /v1/evaluations/overview ...")
    ov = httpx.get(f"{GATEWAY}/v1/evaluations/overview", timeout=10)
    print(f"      status={ov.status_code} body={ov.json()}")
    if ov.status_code != 200:
        print(ov.text)
        return 1

    print("[3/5] Locate or create a terminal task ...")
    listed = httpx.get(f"{GATEWAY}/v1/tasks?limit=30", timeout=10)
    if listed.status_code != 200:
        print(listed.text)
        return 1
    tasks = listed.json().get("tasks") or []
    target = next(
        (t for t in tasks if t.get("status") in ("completed", "failed", "cancelled")),
        None,
    )
    if not target:
        created = httpx.post(
            f"{GATEWAY}/v1/tasks",
            json={"input": {"type": "text", "content": "phase10 evaluation smoke"}},
            timeout=30,
        )
        if created.status_code >= 300:
            print(f"      cannot create task ({created.status_code}): {created.text}")
            print("PHASE10 PARTIAL — overview OK, no terminal task to score")
            return 0
        tid = created.json()["task_id"]
        cancelled = httpx.post(f"{GATEWAY}/v1/tasks/{tid}/cancel", timeout=10)
        print(f"      created+cancelled {tid[:8]} -> {cancelled.status_code}")
        if cancelled.status_code != 200:
            print(cancelled.text)
            return 1
        target = {"task_id": tid, "status": "cancelled"}
        # cancel path may already evaluate; give DB a beat
        time.sleep(0.3)

    tid = target["task_id"]
    print(f"      task={tid[:8]} status={target.get('status')}")

    print("[4/5] POST /v1/tasks/{id}/evaluate ...")
    scored = httpx.post(f"{GATEWAY}/v1/tasks/{tid}/evaluate", timeout=15)
    print(f"      status={scored.status_code}")
    if scored.status_code != 200:
        print(scored.text)
        return 1
    body = scored.json()
    print(f"      grade={body.get('grade')} score={body.get('score')} method={body.get('method')}")
    if body.get("grade") is None or body.get("score") is None:
        print("      missing grade/score")
        return 1

    print("[5/5] GET evaluation + list ...")
    got = httpx.get(f"{GATEWAY}/v1/tasks/{tid}/evaluation", timeout=10)
    listed_ev = httpx.get(f"{GATEWAY}/v1/evaluations?limit=10", timeout=10)
    print(f"      get={got.status_code} list={listed_ev.status_code}")
    if got.status_code != 200 or listed_ev.status_code != 200:
        print(got.text)
        print(listed_ev.text)
        return 1
    items = listed_ev.json().get("evaluations") or []
    print(f"      listed={len(items)} first_grade={(items[0].get('grade') if items else None)}")

    print("PHASE10 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
