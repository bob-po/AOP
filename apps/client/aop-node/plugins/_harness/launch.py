"""Launch a harness virtual agent as an aop-node plugin child.

Does not embed Claude/DeepSeek/Pi/OpenClaw/Hermes. It locates the monorepo
``agents/harness-agent`` + ``packages/*``, injects PYTHONPATH, then runs uvicorn.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIRS = (
    "packages/agent-runtime",
    "packages/a2a-sdk",
    "packages/llm-provider",
    "packages/schemas",
    "packages/common",
)


def find_repo_root(start: Path) -> Path | None:
    cur = start.resolve()
    for p in [cur, *cur.parents]:
        harness = p / "agents" / "harness-agent" / "agent.py"
        runtime = p / "packages" / "agent-runtime"
        if harness.is_file() and runtime.is_dir():
            return p
    return None


def resolve_repo(plugin_dir: Path) -> Path:
    env = (os.environ.get("AOP_REPO_ROOT") or os.environ.get("AOP_HARNESS_ROOT") or "").strip()
    if env:
        p = Path(env).expanduser().resolve()
        if (p / "agents" / "harness-agent" / "agent.py").is_file():
            return p
        if (p / "agent.py").is_file() and p.name == "harness-agent":
            return p.parent.parent
        raise SystemExit(f"AOP_REPO_ROOT/AOP_HARNESS_ROOT is not an AOP repo: {p}")
    found = find_repo_root(plugin_dir) or find_repo_root(Path(__file__))
    if not found:
        raise SystemExit(
            "Cannot find agents/harness-agent. Set AOP_REPO_ROOT to the AOP repo root "
            "or keep this plugin under apps/client/aop-node/plugins/."
        )
    return found


def inject_pythonpath(repo: Path) -> None:
    extras: list[str] = []
    for rel in PACKAGE_DIRS:
        d = repo / rel
        if d.is_dir():
            extras.append(str(d))
    harness = repo / "agents" / "harness-agent"
    extras.append(str(harness))
    existing = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    merged = extras + [p for p in existing if p not in extras]
    os.environ["PYTHONPATH"] = os.pathsep.join(merged)
    for p in reversed(extras):
        if p not in sys.path:
            sys.path.insert(0, p)


def main() -> None:
    plugin_dir = Path(os.environ.get("AOP_PLUGIN_DIR") or os.getcwd()).resolve()
    profile = (os.environ.get("HARNESS_PROFILE") or os.environ.get("AGENT_ID") or "").strip()
    if not profile:
        raise SystemExit("HARNESS_PROFILE (or AGENT_ID) is required")

    port = int(os.environ.get("PORT") or "8011")
    os.environ.setdefault("AGENT_ID", profile)
    os.environ["PORT"] = str(port)
    os.environ["AGENT_URL"] = f"http://127.0.0.1:{port}/"
    os.environ.setdefault("HARNESS_HEARTBEAT", "1")
    os.environ["HARNESS_PROFILE"] = profile

    repo = resolve_repo(plugin_dir)
    harness = repo / "agents" / "harness-agent"
    profile_dir = harness / "profiles" / profile
    if not profile_dir.is_dir():
        raise SystemExit(f"Unknown profile {profile!r} (missing {profile_dir})")

    inject_pythonpath(repo)
    os.chdir(harness)

    host = os.environ.get("HARNESS_HOST") or "127.0.0.1"
    import uvicorn

    uvicorn.run("agent:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
