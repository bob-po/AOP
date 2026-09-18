#!/usr/bin/env python3
"""Phase 7b smoke: marketplace install + health probe offline/online."""

from __future__ import annotations

import argparse
import time

import httpx


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    gateway = args.gateway.rstrip("/")

    print("[1/4] Marketplace catalog ...")
    cat = httpx.get(f"{gateway}/v1/marketplace", timeout=15)
    if cat.status_code >= 300:
        print(cat.status_code, cat.text)
        return 1
    packages = cat.json().get("packages") or []
    print(f"      packages={len(packages)}")
    if len(packages) < 3:
        print("expected at least 3 catalog packages")
        return 1

    print("[2/4] Install all catalog packages ...")
    for pkg in packages:
        r = httpx.post(
            f"{gateway}/v1/marketplace/install",
            json={"package_id": pkg["package_id"]},
            timeout=30,
        )
        print(f"      {pkg['package_id']} -> {r.status_code}")
        if r.status_code >= 300:
            print(r.text)
            return 1

    cat2 = httpx.get(f"{gateway}/v1/marketplace", timeout=15).json()
    installed = [p for p in cat2.get("packages") or [] if p.get("installed")]
    print(f"      installed={len(installed)}")
    if len(installed) < 3:
        print("install incomplete")
        return 1

    print("[3/4] Health probe (expect online) ...")
    probe = httpx.post(f"{gateway}/v1/health/probe", timeout=30)
    if probe.status_code >= 300:
        print(probe.status_code, probe.text)
        return 1
    body = probe.json()
    print(f"      probed={body.get('probed')} online={body.get('online')}")
    if body.get("online", 0) < 1:
        print("expected some online agents while services are up")
        return 1

    # disable one agent and probe again should keep it disabled (monitor skips disabled)
    agent_id = installed[0]["agent"]["agent_id"]
    print(f"[4/4] Disable {agent_id} then probe ...")
    d = httpx.post(f"{gateway}/v1/agents/{agent_id}/disable", timeout=15)
    if d.status_code >= 300:
        print(d.status_code, d.text)
        return 1
    time.sleep(0.3)
    probe2 = httpx.post(f"{gateway}/v1/health/probe", timeout=30).json()
    disabled = next(
        (r for r in probe2.get("results") or [] if r.get("agent_id") == agent_id),
        None,
    )
    print(f"      disabled probe status={disabled.get('status') if disabled else None}")
    if not disabled or disabled.get("status") != "disabled":
        print("disabled agent should remain disabled during probe")
        return 1

    # re-enable
    httpx.post(f"{gateway}/v1/agents/{agent_id}/enable", timeout=15)
    print("PHASE7B OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
