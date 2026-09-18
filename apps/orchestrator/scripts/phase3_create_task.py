#!/usr/bin/env python3
"""Phase 3 smoke: register agents → create task → verify DAG + parallel READY."""

from __future__ import annotations

import argparse
import json
import sys
import time

import httpx


def register(gateway: str, endpoint: str) -> dict:
    resp = httpx.post(
        f"{gateway}/v1/agents/register",
        json={"endpoint": endpoint},
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--skip-register", action="store_true")
    parser.add_argument(
        "--goal",
        default="帮我研究一个 AI 产品，搜索资料并结合知识库分析，然后生成一份报告",
    )
    args = parser.parse_args()
    gateway = args.gateway.rstrip("/")

    if not args.skip_register:
        print("[1/4] Registering agents ...")
        for ep in (
            "http://127.0.0.1:8001",
            "http://127.0.0.1:8002",
            "http://127.0.0.1:8003",
        ):
            try:
                data = register(gateway, ep)
                print(f"      {ep} -> {data}")
            except Exception as exc:  # noqa: BLE001
                print(f"      FAIL {ep}: {exc}")
                return 1
    else:
        print("[1/4] Skip register")

    print("[2/4] Creating task via Gateway ...")
    resp = httpx.post(
        f"{gateway}/v1/tasks",
        json={"input": {"type": "text", "content": args.goal}},
        timeout=30.0,
    )
    if resp.status_code >= 300:
        print("create failed:", resp.status_code, resp.text)
        return 1
    created = resp.json()
    print(json.dumps(created, ensure_ascii=False, indent=2))

    task_id = created["task_id"]
    ready = set(created.get("ready_nodes") or [])
    nodes = {n["id"]: n for n in created.get("nodes") or []}

    print("[3/4] Validating parallel READY roots ...")
    expected_ready = {"search", "rag"}
    if not expected_ready.issubset(ready):
        print(f"      expected ready to include {expected_ready}, got {ready}")
        return 1
    if nodes.get("report", {}).get("status") != "pending":
        print("      report should stay pending until upstream completes")
        return 1
    print(f"      ready={sorted(ready)} report=pending OK")

    print("[4/4] Fetch task + events ...")
    time.sleep(0.2)
    detail = httpx.get(f"{gateway}/v1/tasks/{task_id}", timeout=15.0)
    detail.raise_for_status()
    events = httpx.get(f"{gateway}/v1/tasks/{task_id}/events", timeout=15.0)
    events.raise_for_status()
    print("      status=", detail.json().get("status"))
    print("      events=", len(events.json().get("events") or []))
    for ev in events.json().get("events") or []:
        print(f"      - {ev.get('event_type')}: {ev.get('message')}")

    print("PHASE3 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
