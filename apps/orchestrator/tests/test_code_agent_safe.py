"""Code agent AST sandbox unit tests (run without FastAPI server)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "agents" / "code-agent"))

from agent import SafeEvalError, run_code, safe_eval  # noqa: E402


def test_safe_eval_arithmetic():
    assert safe_eval("1 + 2 * 3") == 7
    assert safe_eval("sum(range(5))") == 10
    assert abs(safe_eval("sqrt(4)") - 2.0) < 1e-9


def test_safe_eval_rejects_import():
    with pytest.raises(SafeEvalError):
        safe_eval("__import__('os').system('echo hi')")
    with pytest.raises(SafeEvalError):
        safe_eval("open('/etc/passwd')")


def test_run_code_ok_and_error():
    ok = run_code("min(3, 1, 2)")
    assert ok["ok"] is True
    assert ok["result"] == 1
    bad = run_code("import os")
    assert bad["ok"] is False
