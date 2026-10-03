#!/usr/bin/env python3
"""One-command local bring-up: infra + orchestrator + worker + outbox + gateway + web + aop-node.

Ctrl+C stops the app processes (Postgres/Redis/MinIO stay up).

  python scripts/dev_up.py
  python scripts/dev_up.py --skip-agents
  python scripts/dev_up.py --legacy-agents   # 5× uvicorn instead of aopd
  python scripts/dev_up.py --skip-web
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / ".aop" / "logs"
PYTHON = sys.executable
COMPOSE_FILE = ROOT / "deployments" / "docker-compose.yml"


def _info(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def _die(msg: str, code: int = 1) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


def _need(cmd: str) -> None:
    if shutil.which(cmd) is None:
        _die(f"missing command: {cmd}")


def _port_open(host: str, port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.4)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _wait_port(host: str, port: int, name: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(host, port):
            print(f"  {name} :{port} OK", flush=True)
            return
        time.sleep(0.5)
    _die(f"timeout waiting for {name} on {host}:{port}")


def _http_ok(url: str) -> bool:
    try:
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                return True
        except urllib.error.HTTPError:
            return True
    except Exception:
        return False


def _wait_http(url: str, name: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _http_ok(url):
            print(f"  {name} {url} OK", flush=True)
            return
        time.sleep(0.6)
    _die(f"timeout waiting for {name}: {url}")


def _compose(args: list[str]) -> None:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), *args]
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        _die(f"docker compose failed: {' '.join(cmd)}")


def _resolve_argv(argv: list[str]) -> list[str]:
    """On Windows, npm/npx live as npm.cmd — bare names fail CreateProcess."""
    exe = argv[0]
    found = shutil.which(exe)
    if found:
        return [found, *argv[1:]]
    if os.name == "nt":
        for ext in (".cmd", ".bat", ".exe"):
            found = shutil.which(exe + ext)
            if found:
                return [found, *argv[1:]]
    return argv


def _spawn(name: str, argv: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    log_f = open(log_path, "ab")
    resolved = _resolve_argv(argv)
    kwargs: dict = {
        "cwd": str(cwd),
        "env": env,
        "stdout": log_f,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    print(f"  start {name}: {' '.join(resolved)}  (log {log_path.relative_to(ROOT)})", flush=True)
    return subprocess.Popen(resolved, **kwargs)


def _harness_profiles() -> list[tuple[str, int]]:
    default = [
        ("claude-code", 8011),
        ("deepseek-harness", 8012),
        ("pi", 8013),
        ("openclaw", 8014),
        ("hermes", 8015),
    ]
    raw = os.getenv("HARNESS_PROFILES", "").strip()
    if not raw:
        return default
    wanted = {p.strip() for p in raw.split(",") if p.strip()}
    return [(n, p) for n, p in default if n in wanted]


def _register_agents(ports: list[int], env: dict[str, str]) -> None:
    import json
    import urllib.error
    import urllib.request

    gateway = env.get("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
    key = (
        env.get("GATEWAY_API_KEY")
        or env.get("AOP_API_KEY")
        or env.get("NEXT_PUBLIC_API_KEY")
        or ""
    )
    for port in ports:
        endpoint = f"http://127.0.0.1:{port}"
        req = urllib.request.Request(
            f"{gateway}/v1/agents/register",
            data=json.dumps({"endpoint": endpoint}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        if key:
            req.add_header("Authorization", f"Bearer {key}")
            req.add_header("X-API-Key", key)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                print(f"  register :{port} -> {resp.status}", flush=True)
        except urllib.error.HTTPError as exc:
            print(f"  register :{port} -> {exc.code} {exc.reason}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  register :{port} error: {exc}", flush=True)


def _stop(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            proc.terminate()
        else:
            proc.send_signal(signal.SIGTERM)
    except OSError:
        pass
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    print(f"  stopped {name}", flush=True)


def _write_aop_node_config(env: dict[str, str]) -> Path:
    """Write .aop/aop-node.toml with an absolute plugins_dir (aopd chdirs to the config folder)."""
    src = ROOT / "apps" / "client" / "aop-node" / "config" / "aop-node.example.toml"
    dest = ROOT / ".aop" / "aop-node.toml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8") if src.is_file() else ""
    plugins = (ROOT / "apps" / "client" / "aop-node" / "plugins").resolve().as_posix()
    gw = env.get("GATEWAY_URL", "http://127.0.0.1:8080").rstrip("/")
    orch = env.get("ORCHESTRATOR_URL", "http://127.0.0.1:8090").rstrip("/")
    key = (
        env.get("GATEWAY_API_KEY")
        or env.get("AOP_API_KEY")
        or env.get("NEXT_PUBLIC_API_KEY")
        or ""
    )
    if text:
        text = text.replace('plugins_dir = "./plugins"', f'plugins_dir = "{plugins}"')
        text = text.replace(
            'gateway_url = "http://127.0.0.1:8080"', f'gateway_url = "{gw}"'
        )
        text = text.replace(
            'orchestrator_url = "http://127.0.0.1:8090"',
            f'orchestrator_url = "{orch}"',
        )
        text = text.replace('api_key = ""', f'api_key = "{key}"')
    else:
        text = (
            f'gateway_url = "{gw}"\n'
            f'orchestrator_url = "{orch}"\n'
            f'api_key = "{key}"\n'
            'node_id = "node-local-1"\n'
            f'plugins_dir = "{plugins}"\n'
            'mgmt_listen = "127.0.0.1:7920"\n'
            "autostart = true\n"
        )
    dest.write_text(text, encoding="utf-8")
    return dest


def _aopd_candidates() -> list[Path]:
    node = ROOT / "apps" / "client" / "aop-node"
    name = "aopd.exe" if os.name == "nt" else "aopd"
    return [
        node / "target" / "release" / name,
        node / "target" / "debug" / name,
    ]


def _ensure_aopd() -> Path | None:
    for p in _aopd_candidates():
        if p.is_file():
            return p
    cargo = shutil.which("cargo") or shutil.which("cargo.exe")
    if not cargo:
        return None
    node = ROOT / "apps" / "client" / "aop-node"
    _info("cargo build -p aopd (first time may take a minute)")
    r = subprocess.run(_resolve_argv(["cargo", "build", "-p", "aopd"]), cwd=str(node))
    if r.returncode != 0:
        return None
    for p in _aopd_candidates():
        if p.is_file():
            return p
    return None


def _start_legacy_agents(
    procs: list[tuple[str, subprocess.Popen]], env: dict[str, str]
) -> None:
    _info("harness agents (legacy uvicorn)")
    agent_cwd = ROOT / "agents" / "harness-agent"
    if not (agent_cwd / "agent.py").exists():
        print("  skip agents: agents/harness-agent/agent.py missing", flush=True)
        return
    profiles = _harness_profiles()
    for profile, port in profiles:
        name = f"agent-{profile}"
        if _port_open("127.0.0.1", port):
            print(f"  skip {name} :{port} already up", flush=True)
            continue
        aenv = env.copy()
        aenv["PORT"] = str(port)
        aenv["AGENT_URL"] = f"http://127.0.0.1:{port}/"
        aenv["HARNESS_PROFILE"] = profile
        aenv["AGENT_ID"] = profile
        aenv["HARNESS_HEARTBEAT"] = aenv.get("HARNESS_HEARTBEAT") or "1"
        aenv.pop("AOP_NODE_MANAGED", None)
        procs.append(
            (
                name,
                _spawn(
                    name,
                    [
                        PYTHON,
                        "-m",
                        "uvicorn",
                        "agent:app",
                        "--host",
                        "0.0.0.0",
                        "--port",
                        str(port),
                    ],
                    cwd=agent_cwd,
                    env=aenv,
                ),
            )
        )
    up_ports: list[int] = []
    for profile, port in profiles:
        deadline = time.time() + 40
        while time.time() < deadline:
            if _http_ok(f"http://127.0.0.1:{port}/health"):
                print(f"  {profile} :{port} OK", flush=True)
                up_ports.append(port)
                break
            time.sleep(0.5)
        else:
            print(f"  {profile} :{port} not healthy (continuing)", flush=True)
    if up_ports:
        _register_agents(up_ports, env)


def _start_aop_node(
    procs: list[tuple[str, subprocess.Popen]], env: dict[str, str]
) -> bool:
    """Start one aopd process. Returns False if caller should use legacy uvicorn."""
    if _http_ok("http://127.0.0.1:7920/health"):
        print("  aop-node already up on :7920 — not spawning extra harness processes", flush=True)
        return True
    node_root = ROOT / "apps" / "client" / "aop-node"
    if not (node_root / "Cargo.toml").is_file():
        return False
    aopd = _ensure_aopd()
    if aopd is None:
        print("  aopd binary/cargo unavailable — falling back to legacy agents", flush=True)
        return False
    cfg = _write_aop_node_config(env)
    aenv = env.copy()
    aenv["AOP_REPO_ROOT"] = str(ROOT)
    aenv["AOP_NODE_CONFIG"] = str(cfg)
    py_home = str(Path(PYTHON).resolve().parent)
    aenv["PATH"] = py_home + os.pathsep + aenv.get("PATH", "")
    _info("aop-node :7920 (supervisor owns harness children)")
    proc = _spawn(
        "aopd",
        [str(aopd), "--config", str(cfg)],
        cwd=node_root,
        env=aenv,
    )
    procs.append(("aopd", proc))
    deadline = time.time() + 90
    while time.time() < deadline:
        if proc.poll() is not None:
            print("  aopd exited immediately — see .aop/logs/aopd.log", flush=True)
            procs.pop()
            return False
        if _http_ok("http://127.0.0.1:7920/health"):
            print("  aop-node :7920 OK", flush=True)
            break
        time.sleep(0.5)
    else:
        print("  aop-node :7920 not healthy (continuing)", flush=True)
        return True
    for profile, port in _harness_profiles():
        end = time.time() + 45
        while time.time() < end:
            if _http_ok(f"http://127.0.0.1:{port}/health"):
                print(f"  {profile} :{port} OK", flush=True)
                break
            time.sleep(0.5)
        else:
            print(f"  {profile} :{port} not healthy yet (aopd still starting)", flush=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="AOP local one-command bring-up")
    parser.add_argument("--skip-agents", action="store_true", help="do not start harness agents")
    parser.add_argument(
        "--legacy-agents",
        action="store_true",
        help="start 5× uvicorn instead of aop-node supervisor",
    )
    parser.add_argument("--skip-web", action="store_true", help="do not start Next.js console")
    parser.add_argument("--no-infra", action="store_true", help="assume postgres/redis/minio already running")
    args = parser.parse_args()

    _need("docker")
    if not args.skip_web:
        _need("npm")
    _need("go")

    env = os.environ.copy()
    env.setdefault("AUTH_REQUIRED", "false")
    env.setdefault("ORCHESTRATOR_URL", "http://127.0.0.1:8090")
    env.setdefault("NEXT_PUBLIC_API_BASE", "http://127.0.0.1:8080")
    # Worker metrics default 9091 collides if orchestrator also binds it — leave default.

    if not args.no_infra:
        _info("infra (postgres redis minio)")
        _compose(["up", "-d", "postgres", "redis", "minio"])
        _wait_port("127.0.0.1", 5432, "postgres")
        _wait_port("127.0.0.1", 6379, "redis")
        _wait_port("127.0.0.1", 9000, "minio")

    _info("migrate")
    mig = subprocess.run(
        [PYTHON, str(ROOT / "infrastructure" / "postgres" / "migrate.py")],
        cwd=str(ROOT),
        env=env,
    )
    if mig.returncode != 0:
        _die("migrate.py failed")

    orch_cwd = ROOT / "apps" / "orchestrator"
    gw_cwd = ROOT / "apps" / "gateway"
    web_cwd = ROOT / "apps" / "web"
    procs: list[tuple[str, subprocess.Popen]] = []

    try:
        _info("orchestrator :8090")
        procs.append(
            (
                "orchestrator",
                _spawn(
                    "orchestrator",
                    [PYTHON, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"],
                    cwd=orch_cwd,
                    env=env,
                ),
            )
        )
        _wait_http("http://127.0.0.1:8090/health", "orchestrator")

        _info("worker")
        worker_env = env.copy()
        worker_env.setdefault("METRICS_PORT", "9092")
        procs.append(
            ("worker", _spawn("worker", [PYTHON, "worker.py"], cwd=orch_cwd, env=worker_env))
        )
        time.sleep(0.8)
        if procs[-1][1].poll() is not None:
            _die("worker exited immediately — see .aop/logs/worker.log")

        _info("outbox")
        procs.append(
            (
                "outbox",
                _spawn(
                    "outbox",
                    [PYTHON, "outbox_processor_service.py"],
                    cwd=orch_cwd,
                    env=env,
                ),
            )
        )
        time.sleep(0.8)
        if procs[-1][1].poll() is not None:
            _die("outbox exited immediately — see .aop/logs/outbox.log")

        _info("gateway :8080")
        procs.append(
            ("gateway", _spawn("gateway", ["go", "run", "./cmd"], cwd=gw_cwd, env=env))
        )
        _wait_http("http://127.0.0.1:8080/health", "gateway", timeout=120)

        if not args.skip_web:
            if not (web_cwd / "node_modules").exists():
                _info("npm install")
                npm_i = subprocess.run(_resolve_argv(["npm", "install"]), cwd=str(web_cwd), env=env)
                if npm_i.returncode != 0:
                    _die("npm install failed")
            _info("web :3000")
            procs.append(
                ("web", _spawn("web", ["npm", "run", "dev"], cwd=web_cwd, env=env))
            )
            _wait_http("http://127.0.0.1:3000", "web", timeout=120)

        if not args.skip_agents:
            legacy = args.legacy_agents or (os.getenv("AOP_LEGACY_AGENTS") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            if legacy or not _start_aop_node(procs, env):
                if not legacy:
                    _info("falling back to legacy harness uvicorn")
                _start_legacy_agents(procs, env)

        print("", flush=True)
        _info("ready")
        print("  Console      http://127.0.0.1:3000")
        print("  Gateway      http://127.0.0.1:8080/health")
        print("  Orchestrator http://127.0.0.1:8090/health")
        print("  aop-node     http://127.0.0.1:7920/health")
        print("  Preflight    http://127.0.0.1:8080/v1/preflight")
        print("  Logs         .aop/logs/")
        print("  Stop apps    Ctrl+C  (containers stay up)", flush=True)

        while True:
            for name, proc in procs:
                code = proc.poll()
                if code is not None:
                    _die(f"{name} exited with {code} — see .aop/logs/{name}.log")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n==> shutting down app processes", flush=True)
        return 0
    finally:
        for name, proc in reversed(procs):
            _stop(proc, name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
