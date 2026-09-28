from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from launch import find_repo_root, resolve_repo


def test_find_repo_from_plugin_tree():
    root = find_repo_root(HERE)
    assert root is not None
    assert (root / "agents" / "harness-agent" / "agent.py").is_file()
    assert resolve_repo(HERE.parent / "claude-code") == root
