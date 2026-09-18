#!/usr/bin/env python3
"""Start all AOP sample agents (Windows-friendly) and register to Gateway."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
AGENTS = [
    ("search-agent", 8001),
    ("rag-agent", 8002),
    ("report-agent", 8003),
    ("analysis-agent", 8004),
    ("image-agent", 8005),
    ("video-agent", 8006),
    ("code-agent", 8007),
    ("browser-agent", 8008),
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


def main() -> int:
    procs: list[subprocess.Popen] = []
    print(f"Python: {PYTHON}")
    for name, port in AGENTS:
        cwd = ROOT / "agents" / name
        if not (cwd / "agent.py").exists():
            print(f"skip missing {name}")
            continue
        # skip if already healthy
        if wait_health(port, timeout=1.0):
            print(f"[skip] {name} already up on :{port}")
            continue
        env = os.environ.copy()
        env["PORT"] = str(port)
        env["AGENT_URL"] = f"http://127.0.0.1:{port}/"
        print(f"[start] {name} :{port}")
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
    for name, port in AGENTS:
        ok = wait_health(port, timeout=25.0)
        print(f"  {name}:{port} -> {'OK' if ok else 'FAIL'}")
        if not ok:
            failed.append(name)
            log_path = ROOT / "agents" / name / f".uvicorn-{port}.log"
            if log_path.exists():
                print(log_path.read_text(encoding="utf-8", errors="ignore")[-500:])

    if failed:
        print("agents failed:", ", ".join(failed))
        return 1

    print(f"Registering to {GATEWAY} ...")
    for name, port in AGENTS:
        endpoint = f"http://127.0.0.1:{port}"
        try:
            r = httpx.post(
                f"{GATEWAY}/v1/agents/register",
                json={"endpoint": endpoint},
                headers=_headers(),
                timeout=20,
            )
            print(f"  register {name} -> {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            print(f"  register {name} error: {exc}")
            return 1

    listed = httpx.get(f"{GATEWAY}/v1/agents", headers=_headers(), timeout=10)
    agents = listed.json().get("agents") or []
    print(f"Registry count: {len(agents)}")
    for a in agents:
        print(f"  - {a.get('name')} [{a.get('status')}] skills={a.get('skills')}")
    print("ALL AGENTS READY")
    # keep children running if we spawned any; otherwise exit
    if procs:
        print(f"Spawned {len(procs)} process(es); exiting without waiting (agents run detached).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
