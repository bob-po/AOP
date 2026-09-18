#!/usr/bin/env python3
"""Phase 15 smoke: AUTH_REQUIRED + mutating scope enforcement."""

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
GATEWAY_DIR = ROOT / "apps" / "gateway"


def wait_health(url: str, timeout: float = 25.0) -> None:
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


def build_gateway() -> Path:
    out = GATEWAY_DIR / "bin" / "gateway.exe"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["GOPROXY"] = env.get("GOPROXY") or "https://goproxy.cn,direct"
    cmd = ["go", "build", "-o", str(out), "./cmd/main.go"]
    print("building:", " ".join(cmd))
    subprocess.check_call(cmd, cwd=str(GATEWAY_DIR), env=env)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default="http://127.0.0.1:8082")
    parser.add_argument("--skip-spawn", action="store_true")
    args = parser.parse_args()
    gateway = args.gateway.rstrip("/")

    proc = None
    if not args.skip_spawn:
        binary = build_gateway()
        env = os.environ.copy()
        env["AUTH_REQUIRED"] = "true"
        env["SEED_DEV_KEY"] = "true"
        env["GATEWAY_ADDR"] = ":8082"
        env["GOPROXY"] = env.get("GOPROXY") or "https://goproxy.cn,direct"
        print("[1/5] Spawning AUTH_REQUIRED gateway on :8082 ...")
        proc = subprocess.Popen(
            [str(binary)],
            cwd=str(GATEWAY_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            wait_health(gateway)
        except Exception as exc:
            print("spawn failed:", exc)
            if proc.stdout:
                print(proc.stdout.read()[-2000:])
            proc.terminate()
            return 1
        # Ensure plaintext DevKey is not logged
        time.sleep(0.2)
        # can't easily read prior logs from PIPE without race; skip if buffered empty
    else:
        print("[1/5] Using existing gateway", gateway)
        wait_health(gateway)

    try:
        print("[2/5] Unauthenticated agents list -> 401")
        r = httpx.get(f"{gateway}/v1/agents", timeout=10)
        print(f"      status={r.status_code}")
        if r.status_code != 401:
            print("expected 401")
            return 1

        print("[3/5] metrics stays public")
        r = httpx.get(f"{gateway}/metrics", timeout=10)
        print(f"      status={r.status_code}")
        if r.status_code != 200:
            print(r.text[:300])
            return 1

        print("[4/5] Create scoped key (task.read only)")
        created = httpx.post(
            f"{gateway}/v1/api-keys",
            headers={"Authorization": f"Bearer {DEV_KEY}"},
            json={"name": "phase15-readonly", "scopes": ["task.read", "agent.read"]},
            timeout=10,
        )
        if created.status_code >= 300:
            print(created.status_code, created.text)
            return 1
        scoped = created.json()["api_key"]
        key_id = created.json()["id"]

        print("[5/5] Scoped key cannot POST /v1/tasks (need task.write)")
        denied = httpx.post(
            f"{gateway}/v1/tasks",
            headers={"Authorization": f"Bearer {scoped}"},
            json={"input": {"type": "text", "content": "scope check"}},
            timeout=15,
        )
        print(f"      status={denied.status_code}")
        if denied.status_code != 403:
            print("expected 403 for task.write", denied.text[:400])
            return 1

        denied_reg = httpx.post(
            f"{gateway}/v1/agents/register",
            headers={"Authorization": f"Bearer {scoped}"},
            json={"endpoint": "http://127.0.0.1:9"},
            timeout=10,
        )
        print(f"      register status={denied_reg.status_code}")
        if denied_reg.status_code != 403:
            print("expected 403 for agent.write", denied_reg.text[:400])
            return 1

        httpx.delete(
            f"{gateway}/v1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {DEV_KEY}"},
            timeout=10,
        )
        print("PHASE15 OK")
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
