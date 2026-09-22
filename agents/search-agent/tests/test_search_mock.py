"""Search mock-mode tests (no network)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from search import mock_results, run_search  # noqa: E402


def test_mock_results_shape():
    rows = mock_results("AOP platform")
    assert len(rows) >= 1
    assert "title" in rows[0] and "url" in rows[0]


def test_run_search_mock_mode():
    os.environ["SEARCH_MODE"] = "mock"
    os.environ["SEARCH_FETCH_PAGES"] = "0"
    payload = asyncio.run(run_search("multi agent orchestration"))
    assert payload["source"] == "mock"
    assert payload["results"]
    assert "Search results for" in payload["summary"]
    assert "content" not in payload["results"][0]
