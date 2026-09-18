#!/usr/bin/env python3
"""Phase 8 smoke: API key auth required / optional modes."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

DEV_KEY = "aop_sk_dev_local_0000000000000001"
ROOT = Path(__file__).resolve().parents[3]
GATEWAY_BIN = ROOT / "apps" / "gateway" / "bin" / "gateway.exe"


def wait_health(url: str, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"{url}/health", timeout=2.0)
            if r.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"gateway not healthy: {url}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8081")
    parser.add_argument("--skip-spawn", action="store_true", help="use already running AUTH_REQUIRED gateway")
    args = parser.parse_args()
    gateway = args.gateway.rstrip("/")

    proc = None
    if not args.skip_spawn:
        if not GATEWAY_BIN.exists():
            print("missing gateway binary:", GATEWAY_BIN)
            return 1
        env = os.environ.copy()
        env["AUTH_REQUIRED"] = "true"
        env["GATEWAY_ADDR"] = ":8081"
        env["GOPROXY"] = env.get("GOPROXY") or "https://goproxy.cn,direct"
        print("[1/4] Spawning AUTH_REQUIRED gateway on :8081 ...")
        proc = subprocess.Popen(
            [str(GATEWAY_BIN)],
            cwd=str(GATEWAY_BIN.parent.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_health(gateway)
        except Exception as exc:
            print("spawn failed:", exc)
            proc.terminate()
            return 1
    else:
        print("[1/4] Using existing gateway", gateway)
        wait_health(gateway)

    try:
        print("[2/4] Unauthenticated request should be 401 ...")
        r = httpx.get(f"{gateway}/v1/agents", timeout=10)
        print(f"      status={r.status_code}")
        if r.status_code != 401:
            print("expected 401 without api key")
            return 1

        print("[3/4] Authenticated list agents ...")
        r = httpx.get(
            f"{gateway}/v1/agents",
            headers={"Authorization": f"Bearer {DEV_KEY}"},
            timeout=10,
        )
        print(f"      status={r.status_code}")
        if r.status_code != 200:
            print(r.text)
            return 1

        print("[4/4] Create / list api keys ...")
        created = httpx.post(
            f"{gateway}/v1/api-keys",
            headers={"Authorization": f"Bearer {DEV_KEY}"},
            json={"name": "smoke-key", "scopes": ["task.read", "agent.read"]},
            timeout=10,
        )
        if created.status_code >= 300:
            print(created.status_code, created.text)
            return 1
        body = created.json()
        new_key = body.get("api_key")
        key_id = body.get("id")
        print(f"      created prefix={body.get('key_prefix')}")
        if not new_key:
            print("create response missing api_key")
            return 1

        listed = httpx.get(
            f"{gateway}/v1/api-keys",
            headers={"Authorization": f"Bearer {DEV_KEY}"},
            timeout=10,
        )
        if listed.status_code != 200:
            print(listed.status_code, listed.text)
            return 1

        # scoped key cannot manage api keys when AUTH on
        denied = httpx.get(
            f"{gateway}/v1/api-keys",
            headers={"Authorization": f"Bearer {new_key}"},
            timeout=10,
        )
        print(f"      scoped key list api-keys -> {denied.status_code}")
        if denied.status_code != 403:
            print("expected 403 for non-admin key managing api-keys")
            return 1

        rev = httpx.delete(
            f"{gateway}/v1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {DEV_KEY}"},
            timeout=10,
        )
        print(f"      revoke -> {rev.status_code}")
        if rev.status_code != 200:
            print(rev.text)
            return 1

        print("PHASE8 OK")
        print(f"dev key: {DEV_KEY}")
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
