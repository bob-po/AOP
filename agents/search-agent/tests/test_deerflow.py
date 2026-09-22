"""DeerFlow backend unit tests (mocked HTTP, no real DeerFlow)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from deerflow_client import deerflow_search  # noqa: E402
from search import run_search  # noqa: E402


SSE = (
    "event: tool_call_result\n"
    'data: {"agent":"researcher","content":"[{\\"title\\":\\"About DeerFlow\\",'
    '\\"url\\":\\"https://example.com/deerflow\\",\\"content\\":\\"Deep research framework.\\"}]"}\n'
    "\n"
    "event: message_chunk\n"
    'data: {"agent":"reporter","content":"DeerFlow is a deep research framework."}\n'
    "\n"
    "event: citations\n"
    'data: {"citations":[{"url":"https://example.com/deerflow","title":"About DeerFlow",'
    '"content":"Deep research framework."}]}\n'
    "\n"
)


class _StreamResp:
    status_code = 200

    async def aiter_text(self):
        yield SSE

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


def test_deerflow_search_maps_sse(monkeypatch):
    monkeypatch.setenv("DEERFLOW_URL", "http://deerflow.test:8000")
    monkeypatch.setenv("DEERFLOW_TIMEOUT", "30")

    client = AsyncMock()
    client.stream = MagicMock(return_value=_StreamResp())
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("deerflow_client.httpx.AsyncClient", return_value=client):
        payload = asyncio.run(deerflow_search("what is deerflow", limit=5))

    assert payload is not None
    assert payload["source"] == "deerflow"
    assert payload["answer"].startswith("DeerFlow is")
    assert payload["results"][0]["url"] == "https://example.com/deerflow"
    client.stream.assert_called()


def test_run_search_prefers_deerflow_in_auto(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "auto")
    monkeypatch.setenv("DEERFLOW_URL", "http://deerflow.test:8000")
    monkeypatch.setenv("SEARCH_FETCH_PAGES", "0")

    fake = {
        "query": "q",
        "source": "deerflow",
        "results": [{"title": "T", "url": "https://example.com", "snippet": "s"}],
        "answer": "Answer text",
        "tried": ["deerflow"],
        "summary": "Search results for: q\nSource: deerflow\n\nAnswer text",
    }
    with patch("search.deerflow_search", new=AsyncMock(return_value=fake)):
        payload = asyncio.run(run_search("q"))
    assert payload["source"] == "deerflow"
    assert "Answer text" in payload["summary"]
    assert payload["answer"] == "Answer text"


def test_run_search_deerflow_mode_falls_back_without_url(monkeypatch):
    monkeypatch.setenv("SEARCH_MODE", "deerflow")
    monkeypatch.delenv("DEERFLOW_URL", raising=False)
    monkeypatch.setenv("SEARCH_FETCH_PAGES", "0")
    payload = asyncio.run(run_search("offline"))
    assert payload["source"] == "mock-fallback"
