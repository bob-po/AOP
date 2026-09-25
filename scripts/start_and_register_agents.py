#!/usr/bin/env python3
"""Start harness virtual agents (Windows-friendly) and register to Gateway.

One profile per harness product: ``claude-code``, ``deepseek-harness``, ``pi``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

# (profile dir name / agent_key, port)
HARNESS_PROFILES = [
    ("claude-code", 8011),
    ("deepseek-harness", 8012),
    ("pi", 8013),
]

GATEWAY = os.getenv("GATEWAY_URL", "http://127.0.0.1:8080")
API_KEY = (
    os.getenv("GATEWAY_API_KEY")
    or os.getenv("AOP_API_KEY")
    or os.getenv("NEXT_PUBLIC_API_KEY")
    or ""
)
PYTHON = sys.executable


def _headers() -> dict[str, str]:
    if not API_KEY:
        return {}
    return {"Authorization": f"Bearer {API_KEY}", "X-API-Key": API_KEY}


def wait_health(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def _harness_enabled() -> bool:
    flag = os.getenv("HARNESS_ENABLED", "1").lower()
    if flag in {"0", "false", "off", "no"}:
        return False
    return True


def _selected_harness_profiles() -> list[tuple[str, int]]:
    raw = os.getenv("HARNESS_PROFILES", "").strip()
    if not raw:
        return list(HARNESS_PROFILES)
    wanted = {p.strip() for p in raw.split(",") if p.strip()}
    return [(n, p) for n, p in HARNESS_PROFILES if n in wanted]


def main() -> int:
    procs: list[subprocess.Popen] = []
    print(f"Python: {PYTHON}")
    if not _harness_enabled():
        print("HARNESS_ENABLED=0 — nothing to start")
        return 0

    selected = _selected_harness_profiles()
    if not selected:
        print("No harness profiles selected")
        return 1

    print(f"Harness profiles: {', '.join(n for n, _ in selected)}")
    cwd = ROOT / "agents" / "harness-agent"
    if not (cwd / "agent.py").exists():
        print("agents/harness-agent missing")
        return 1

    health_targets: list[tuple[str, int]] = []
    for profile, port in selected:
        label = f"harness-agent:{profile}"
        health_targets.append((label, port))
        if wait_health(port, timeout=1.0):
            print(f"[skip] {label} already up on :{port}")
            continue
        env = os.environ.copy()
        env["PORT"] = str(port)
        env["AGENT_URL"] = f"http://127.0.0.1:{port}/"
        env["HARNESS_PROFILE"] = profile
        env["AGENT_ID"] = profile
        env["HARNESS_HEARTBEAT"] = env.get("HARNESS_HEARTBEAT") or "1"

        print(f"[start] {label} :{port}")
        log_path = cwd / f".uvicorn-{port}.log"
        log_f = open(log_path, "w", encoding="utf-8")
        procs.append(
            subprocess.Popen(
                [PYTHON, "-m", "uvicorn", "agent:app", "--host", "0.0.0.0", "--port", str(port)],
                cwd=str(cwd),
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
            )
        )
        time.sleep(0.8)

    print("Waiting for health ...")
    failed = []
    for label, port in health_targets:
        ok = wait_health(port, timeout=25.0)
        print(f"  {label}:{port} -> {'OK' if ok else 'FAIL'}")
        if not ok:
            failed.append(label)
            log_path = cwd / f".uvicorn-{port}.log"
            if log_path.exists():
                print(log_path.read_text(encoding="utf-8", errors="ignore")[-500:])

    if failed:
        print("agents failed:", ", ".join(failed))
        return 1

    print(f"Registering to {GATEWAY} ...")
    for label, port in health_targets:
        endpoint = f"http://127.0.0.1:{port}"
        try:
            r = httpx.post(
                f"{GATEWAY}/v1/agents/register",
                json={"endpoint": endpoint},
                headers=_headers(),
                timeout=20,
            )
            print(f"  register {label} -> {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            print(f"  register {label} error: {exc}")
            return 1

    listed = httpx.get(f"{GATEWAY}/v1/agents", headers=_headers(), timeout=10)
    agents = listed.json().get("agents") or []
    print(f"Registry count: {len(agents)}")
    for a in agents:
        print(f"  - {a.get('name')} [{a.get('status')}] skills={a.get('skills')}")
    print("ALL HARNESS AGENTS READY")
    if procs:
        print(f"Spawned {len(procs)} process(es); exiting without waiting (agents run detached).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
