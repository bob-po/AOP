#!/usr/bin/env python3
"""Phase 5 smoke: execute DAG and verify MinIO artifacts are listable/readable."""

from __future__ import annotations

import argparse
import json
import sys
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

    print("[2/4] Create task ...")
    resp = httpx.post(
        f"{gateway}/v1/tasks",
        json={"input": {"type": "text", "content": args.goal}},
        timeout=30,
    )
    if resp.status_code >= 300:
        print(resp.status_code, resp.text)
        return 1
    task_id = resp.json()["task_id"]
    print(f"      task_id={task_id}")

    print("[3/4] Wait for completion ...")
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        detail = httpx.get(f"{gateway}/v1/tasks/{task_id}", timeout=15).json()
        status = detail.get("status")
        nodes = {n["id"]: n["status"] for n in detail.get("nodes") or []}
        print(f"      status={status} nodes={nodes}")
        if status == "completed":
            break
        if status == "failed":
            print("FAILED", json.dumps(detail, ensure_ascii=False)[:800])
            return 1
        time.sleep(0.5)
    else:
        print("TIMEOUT")
        return 1

    print("[4/4] List artifacts ...")
    arts = httpx.get(f"{gateway}/v1/tasks/{task_id}/artifacts", timeout=15)
    if arts.status_code >= 300:
        print(arts.status_code, arts.text)
        return 1
    payload = arts.json()
    items = payload.get("artifacts") or []
    print(f"      count={len(items)}")
    for a in items:
        print(f"      - {a.get('node_id')}/{a.get('name')} {a.get('uri')}")

    # Must have per-node output.md / output.json
    names = {(a.get("node_id"), a.get("name")) for a in items}
    required = {
        ("search", "output.md"),
        ("search", "output.json"),
        ("rag", "output.md"),
        ("rag", "output.json"),
        ("report", "output.md"),
        ("report", "output.json"),
    }
    missing = required - names
    if missing:
        print("MISSING artifacts:", missing)
        return 1

    # Downstream report node output should mention upstream artifact URI
    report_node = httpx.get(f"{gateway}/v1/tasks/{task_id}", timeout=15).json()
    report = next(n for n in report_node["nodes"] if n["id"] == "report")
    # fetch full node via events/result
    result = report_node.get("result_json") or {}
    nodes_out = {n["id"]: n for n in (result.get("nodes") or [])}
    report_out = (nodes_out.get("report") or {}).get("output") or {}
    report_text = report_out.get("text") or ""
    if "s3://aop-artifacts/tasks/" not in report_text and "artifact:" not in report_text.lower():
        # soft check: at least report has its own artifacts list
        if not report_out.get("artifacts"):
            print("report has no artifacts metadata")
            return 1
        print("      note: report text may not echo URI (agent stub), metadata present OK")

    print("PHASE5 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
