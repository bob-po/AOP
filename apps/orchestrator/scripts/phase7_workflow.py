#!/usr/bin/env python3
"""Phase 7 smoke: list/create workflow → run → wait completed."""

from __future__ import annotations

import argparse
import json
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--goal",
        default="用 researcher 调研一个 AI 产品，整理公开资料并给出研究摘要",
    )
    args = parser.parse_args()
    gateway = args.gateway.rstrip("/")

    print("[1/4] Register agents ...")
    for ep in (
        "http://127.0.0.1:8011",
    ):
        r = httpx.post(f"{gateway}/v1/agents/register", json={"endpoint": ep}, timeout=30)
        print(f"      {ep} -> {r.status_code}")
        if r.status_code >= 300:
            print(r.text)
            return 1

    print("[2/4] List workflows (auto-seed default) ...")
    resp = httpx.get(f"{gateway}/v1/workflows", timeout=15)
    if resp.status_code >= 300:
        print(resp.status_code, resp.text)
        return 1
    workflows = resp.json().get("workflows") or []
    print(f"      count={len(workflows)}")
    if not workflows:
        print("      creating custom workflow ...")
        created = httpx.post(
            f"{gateway}/v1/workflows",
            json={
                "name": "Research Pipeline",
                "description": "web-research -> research-summarize -> code-assist",
                "dag": {
                    "nodes": [
                        {"id": "research", "skill": "web-research"},
                        {
                            "id": "summarize",
                            "skill": "research-summarize",
                            "depends_on": ["research"],
                        },
                        {
                            "id": "code",
                            "skill": "code-assist",
                            "depends_on": ["summarize"],
                        },
                    ]
                },
            },
            timeout=15,
        )
        if created.status_code >= 300:
            print(created.status_code, created.text)
            return 1
        wf = created.json()
    else:
        wf = workflows[0]
    print(f"      using {wf.get('workflow_key')} id={wf.get('workflow_id')}")

    print("[3/4] Run workflow ...")
    run = httpx.post(
        f"{gateway}/v1/workflows/{wf['workflow_id']}/run",
        json={"input": {"type": "text", "content": args.goal}},
        timeout=30,
    )
    if run.status_code >= 300:
        print(run.status_code, run.text)
        return 1
    body = run.json()
    task_id = body["task_id"]
    print(
        f"      task_id={task_id} source={body.get('planner', {}).get('method')} "
        f"nodes={[n['id'] for n in body.get('plan', {}).get('nodes', [])]}"
    )
    if body.get("planner", {}).get("method") != "workflow":
        print("expected planner.method=workflow")
        return 1

    print("[4/4] Wait for completion ...")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        detail = httpx.get(f"{gateway}/v1/tasks/{task_id}", timeout=15).json()
        status = detail.get("status")
        nodes = {n["id"]: n["status"] for n in detail.get("nodes") or []}
        print(f"      status={status} nodes={nodes}")
        if status == "completed":
            events = httpx.get(f"{gateway}/v1/tasks/{task_id}/events", timeout=15).json()
            planned = next(
                (e for e in events.get("events") or [] if e.get("event_type") == "task.planned"),
                None,
            )
            if planned and "Workflow" not in (planned.get("message") or ""):
                print("warn: planned message did not mention Workflow:", planned)
            print("PHASE7 OK")
            return 0
        if status == "failed":
            print("FAILED", json.dumps(detail, ensure_ascii=False)[:800])
            return 1
        time.sleep(0.5)

    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
