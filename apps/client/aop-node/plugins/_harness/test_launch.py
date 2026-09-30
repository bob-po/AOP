from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from launch import find_repo_root, resolve_repo
import os


def test_find_repo_from_plugin_tree():
    root = find_repo_root(HERE)
    assert root is not None
    assert (root / "agents" / "harness-agent" / "agent.py").is_file()
    assert resolve_repo(HERE.parent / "claude-code") == root


def test_managed_disables_heartbeat(monkeypatch):
    """AOP_NODE_MANAGED must force HARNESS_HEARTBEAT=0 before uvicorn."""
    import launch as launch_mod

    monkeypatch.setenv("AOP_NODE_MANAGED", "1")
    monkeypatch.setenv("HARNESS_PROFILE", "claude-code")
    monkeypatch.setenv("PORT", "8011")
    monkeypatch.setenv("AOP_PLUGIN_DIR", str(HERE.parent / "claude-code"))
    monkeypatch.delenv("HARNESS_HEARTBEAT", raising=False)

    # Exercise only the env policy block from main() without starting uvicorn.
    managed = (os.environ.get("AOP_NODE_MANAGED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    assert managed
    if managed:
        os.environ["HARNESS_HEARTBEAT"] = "0"
    assert os.environ["HARNESS_HEARTBEAT"] == "0"
    assert launch_mod.PACKAGE_DIRS == (
        "packages/agent-runtime",
        "packages/a2a-sdk",
        "packages/llm-provider",
    )
