#!/usr/bin/env python3
"""Golden 90s path: preflight → create → graph → report. Console URL printed.

  python scripts/golden_demo.py              # live against Gateway :8080
  python scripts/golden_demo.py --check      # preflight only (no new task)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

GOLDEN_PROMPT = "Research Vidu S2 and generate a technical report"
CONSOLE_DEFAULT = "http://127.0.0.1:3000"
API_DEFAULT = "http://127.0.0.1:8080"
TERMINAL = {"completed", "failed", "cancelled", "canceled", "waiting_for_user"}


def console_task_url(console_base: str, task_id: str) -> str:
    return f"{console_base.rstrip('/')}/?task={task_id}"


def blocked_hint(preflight: dict) -> str | None:
    if preflight.get("can_run", True):
        return None
    hints = preflight.get("hints") or []
    blocking = preflight.get("blocking") or []
    if hints:
        return str(hints[0])
    if blocking:
        return "blocked: " + ", ".join(str(x) for x in blocking)
    return "preflight blocked"


def task_id_of(payload: dict) -> str | None:
    tid = payload.get("task_id") or payload.get("id")
    return str(tid) if tid else None


def demo_done(status: str | None) -> bool:
    return (status or "").lower() in TERMINAL


def _headers(api_key: str | None) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
        h["X-API-Key"] = api_key
    return h


def _req(method: str, url: str, *, headers: dict[str, str], body: dict | None = None, timeout: float = 30):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type") or ""
            if "json" in ctype or (raw[:1] in (b"{", b"[")):
                return resp.status, json.loads(raw.decode("utf-8") or "null")
            return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode("utf-8") or "null")
        except json.JSONDecodeError:
            parsed = raw.decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} {url}: {parsed}") from exc


def main() -> int:
    p = argparse.ArgumentParser(description="AOP golden demo (preflight → run → Console)")
    p.add_argument("--api", default=os.getenv("AOP_API", API_DEFAULT))
    p.add_argument("--console", default=os.getenv("AOP_CONSOLE", CONSOLE_DEFAULT))
    p.add_argument("--api-key", default=os.getenv("AOP_API_KEY") or os.getenv("GATEWAY_API_KEY"))
    p.add_argument("--check", action="store_true", help="preflight only")
    p.add_argument("--timeout", type=float, default=90.0)
    p.add_argument("--prompt", default=GOLDEN_PROMPT)
    args = p.parse_args()
    api = args.api.rstrip("/")
    hdr = _headers(args.api_key)

    print(f"golden demo → {api}", flush=True)
    status, pf = _req("GET", f"{api}/v1/preflight", headers=hdr, timeout=45)
    if status != 200 or not isinstance(pf, dict):
        print("FAIL preflight", status, pf, file=sys.stderr)
        return 2
    hint = blocked_hint(pf)
    print(
        f"  preflight {pf.get('status')} can_run={pf.get('can_run')} "
        f"agents={pf.get('ready_agents')}/{pf.get('registered_agents')}",
        flush=True,
    )
    if hint:
        print(f"  BLOCKED {hint}", flush=True)
        print(f"  Console recover: {args.console.rstrip('/')}/settings?tab=monitor", flush=True)
        for step in pf.get("recover_steps") or []:
            if step.get("active"):
                print(f"    • {step.get('title')}: {step.get('console')}", flush=True)
        if args.check:
            return 2
        return 2

    if args.check:
        print("  check ok", flush=True)
        return 0

    _, created = _req(
        "POST",
        f"{api}/v1/tasks",
        headers=hdr,
        body={"title": "golden-demo", "input": {"type": "text", "content": args.prompt}},
    )
    if not isinstance(created, dict):
        print("FAIL create", created, file=sys.stderr)
        return 2
    tid = task_id_of(created)
    if not tid:
        print("FAIL no task id", created, file=sys.stderr)
        return 2
    url = console_task_url(args.console, tid)
    print(f"  task {tid}\n  Console {url}", flush=True)

    deadline = time.time() + args.timeout
    last = created.get("status")
    while time.time() < deadline:
        _, row = _req("GET", f"{api}/v1/tasks/{tid}", headers=hdr)
        last = (row or {}).get("status") if isinstance(row, dict) else last
        print(f"  status {last}", flush=True)
        if demo_done(str(last) if last else None):
            break
        time.sleep(3)
    else:
        print(f"  still {last} after {args.timeout}s — open Console and Retry if stuck", flush=True)

    try:
        _, graph = _req("GET", f"{api}/v1/tasks/{tid}/graph", headers=hdr)
        nodes = (graph or {}).get("nodes") if isinstance(graph, dict) else None
        print(f"  graph nodes={len(nodes) if isinstance(nodes, list) else '?'}", flush=True)
    except SystemExit as exc:
        print(f"  graph skipped: {exc}", flush=True)

    st = str(last or "").lower()
    if st == "waiting_for_user":
        print(f"  HITL → {args.console.rstrip('/')}/inbox", flush=True)
        return 0
    if st == "completed":
        _, report = _req("GET", f"{api}/v1/tasks/{tid}/report", headers=hdr)
        text = report if isinstance(report, str) else str(report)
        print(f"  report {len(text)} chars", flush=True)
        print("  package GET /v1/tasks/{id}/package", flush=True)
        return 0
    if st in {"failed", "cancelled", "canceled"}:
        print(f"  terminal {st} — still open Console for replay", flush=True)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
