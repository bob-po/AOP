#!/usr/bin/env python3
"""Register harness virtual agents to Gateway (docker single-node)."""

from __future__ import annotations

import os
import sys
import time

import httpx

GATEWAY = os.getenv("GATEWAY_URL", "http://gateway:8080").rstrip("/")
API_KEY = (
    os.getenv("GATEWAY_API_KEY")
    or os.getenv("AOP_API_KEY")
    or os.getenv("NEXT_PUBLIC_API_KEY")
    or ""
)

# (name, endpoint env, default URL)
AGENTS = [
    ("claude-coder", "AOP_AGENT_CLAUDE_CODER_URL", "http://claude-coder:8011"),
    ("claude-researcher", "AOP_AGENT_CLAUDE_RESEARCHER_URL", "http://claude-researcher:8012"),
    ("pi-coder", "AOP_AGENT_PI_CODER_URL", "http://pi-coder:8013"),
    ("pi-researcher", "AOP_AGENT_PI_RESEARCHER_URL", "http://pi-researcher:8014"),
    ("deepseek-coder", "AOP_AGENT_DEEPSEEK_CODER_URL", "http://deepseek-coder:8015"),
    ("deepseek-researcher", "AOP_AGENT_DEEPSEEK_RESEARCHER_URL", "http://deepseek-researcher:8016"),
]


def wait(url: str, timeout: float = 120.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=3.0)
            if r.status_code < 500:
                return
        except Exception:
            pass
        time.sleep(1.5)
    raise RuntimeError(f"timeout waiting for {url}")


def _headers() -> dict[str, str]:
    if not API_KEY:
        return {}
    return {"Authorization": f"Bearer {API_KEY}", "X-API-Key": API_KEY}


def main() -> int:
    print(f"gateway={GATEWAY} auth={'on' if API_KEY else 'off'}")
    wait(f"{GATEWAY}/health")
    for name, env_key, default in AGENTS:
        ep = (os.getenv(env_key) or default).rstrip("/")
        wait(f"{ep}/health")
        print(f"register {name} -> {ep}")
        for attempt in range(8):
            try:
                r = httpx.post(
                    f"{GATEWAY}/v1/agents/register",
                    json={"endpoint": ep},
                    headers=_headers(),
                    timeout=30,
                )
                print(f"  status={r.status_code} body={r.text[:200]}")
                if r.status_code < 300:
                    break
            except Exception as exc:  # noqa: BLE001
                print(f"  attempt {attempt+1} error: {exc}")
            time.sleep(2)
        else:
            print(f"FAILED register {name}")
            return 1
    listed = httpx.get(f"{GATEWAY}/v1/agents", headers=_headers(), timeout=15)
    print("agents:", listed.text[:800])
    print("REGISTER_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
