#!/usr/bin/env python3
"""Phase 2 smoke: register harness agent → route by skill → A2A execute."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ORCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_ROOT = REPO_ROOT / "packages" / "a2a-sdk"

for path in (ORCH_ROOT, SDK_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from executor import A2AExecutor  # noqa: E402
from router import AgentRouter, RouterError, normalize_endpoint  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2 register + route + execute")
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    parser.add_argument("--agent", default="http://127.0.0.1:8011")
    parser.add_argument("--skill", default="code-assist")
    parser.add_argument("--query", default="A2A Agent Registry")
    parser.add_argument("--skip-register", action="store_true")
    args = parser.parse_args()

    gateway = args.gateway.rstrip("/")
    agent_url = args.agent.rstrip("/")

    if not args.skip_register:
        print(f"[1/4] Registering agent {agent_url} via {gateway} ...")
        resp = httpx.post(
            f"{gateway}/v1/agents/register",
            json={"endpoint": agent_url},
            timeout=30.0,
        )
        if resp.status_code >= 300:
            print("register failed:", resp.status_code, resp.text)
            return 1
        print("      ", json.dumps(resp.json(), ensure_ascii=False))
    else:
        print("[1/4] Skip register")

    print(f"[2/4] Listing agents skill={args.skill!r} status=online ...")
    resp = httpx.get(
        f"{gateway}/v1/agents",
        params={"skill": args.skill, "status": "online"},
        timeout=15.0,
    )
    resp.raise_for_status()
    agents = resp.json().get("agents") or []
    print(f"      found={len(agents)}")
    for a in agents:
        print(f"      - {a.get('agent_key')} status={a.get('status')} endpoint={a.get('endpoint')}")

    print(f"[3/4] Router.select(skill={args.skill!r}) ...")
    router = AgentRouter()
    try:
        routed = router.select(args.skill)
    except RouterError as exc:
        print("route failed:", exc)
        return 1
    endpoint = normalize_endpoint(routed.endpoint)
    print(
        f"      selected={routed.agent_key} id={routed.agent_id} "
        f"endpoint={endpoint} source={routed.source}"
    )

    print(f"[4/4] Execute via A2A query={args.query!r} ...")
    result = A2AExecutor().execute(endpoint, args.query, skill_id=args.skill)
    print(f"      task={result.task.id} status={result.task.status.value}")
    if result.text:
        print("--- text ---")
        print(result.text[:500] + ("..." if len(result.text) > 500 else ""))

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
