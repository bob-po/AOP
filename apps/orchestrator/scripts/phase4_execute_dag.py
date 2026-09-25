#!/usr/bin/env python3
"""Phase 4 smoke: create DAG task and wait until worker completes all nodes."""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--goal",
        default="用 researcher 调研一个 AI 产品，整理公开资料并给出研究摘要",
    )
    parser.add_argument("--skip-register", action="store_true")
    args = parser.parse_args()
    gateway = args.gateway.rstrip("/")

    if not args.skip_register:
        print("[1/3] Register agents ...")
        for ep in (
            "http://127.0.0.1:8011",
            "http://127.0.0.1:8012",
            "http://127.0.0.1:8015",
        ):
            r = httpx.post(f"{gateway}/v1/agents/register", json={"endpoint": ep}, timeout=30)
            print(f"      {ep} -> {r.status_code} {r.text[:120]}")
            if r.status_code >= 300:
                return 1
    else:
        print("[1/3] Skip register")

    print("[2/3] Create task ...")
    resp = httpx.post(
        f"{gateway}/v1/tasks",
        json={"input": {"type": "text", "content": args.goal}},
        timeout=30,
    )
    if resp.status_code >= 300:
        print(resp.status_code, resp.text)
        return 1
    created = resp.json()
    task_id = created["task_id"]
    print(f"      task_id={task_id} status={created.get('status')} enqueued={created.get('enqueued_nodes')}")
    print(f"      plan={[n['id'] for n in created.get('plan', {}).get('nodes', [])]}")

    print("[3/3] Waiting for worker to complete ...")
    deadline = time.time() + args.timeout
    last_status = None
    while time.time() < deadline:
        detail = httpx.get(f"{gateway}/v1/tasks/{task_id}", timeout=15).json()
        status = detail.get("status")
        nodes = {n["id"]: n["status"] for n in detail.get("nodes") or []}
        if status != last_status:
            print(f"      status={status} nodes={nodes}")
            last_status = status
        if status == "completed":
            events = httpx.get(f"{gateway}/v1/tasks/{task_id}/events", timeout=15).json()
            print("      events:")
            for ev in events.get("events") or []:
                print(f"        - {ev.get('event_type')}: {ev.get('message')}")
            result = detail.get("result_json")
            if result:
                summary = result.get("summary") if isinstance(result, dict) else str(result)
                print("--- summary (truncated) ---")
                print((summary or "")[:600])
            print("PHASE4 OK")
            return 0
        if status == "failed":
            print("FAILED:", json.dumps(detail, ensure_ascii=False, indent=2)[:1000])
            return 1
        time.sleep(0.5)

    print("TIMEOUT waiting for completion")
    detail = httpx.get(f"{gateway}/v1/tasks/{task_id}", timeout=15).json()
    print(json.dumps(detail, ensure_ascii=False, indent=2)[:1500])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
