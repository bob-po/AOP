"""Page fetch helpers — offline unit tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from page_fetch import (  # noqa: E402
    enrich_results_with_pages,
    extract_page_text,
    fetch_url_sync,
    is_public_http_url,
)


def test_rejects_private_urls():
    assert not is_public_http_url("http://127.0.0.1/secret")
    assert not is_public_http_url("http://localhost/x")
    assert not is_public_http_url("file:///etc/passwd")
    assert is_public_http_url("https://example.com/article")


def test_extract_page_text_strips_markup():
    html = "<html><head><title>T</title><script>bad()</script></head>"
    html += "<body><article><h1>Hello</h1><p>World content here.</p></article></body></html>"
    text = extract_page_text(html, limit=200)
    assert "Hello" in text
    assert "World" in text
    assert "bad()" not in text


def test_enrich_attaches_content(monkeypatch):
    monkeypatch.setenv("SEARCH_FETCH_PAGES", "1")

    fake = MagicMock()
    fake.status_code = 200
    fake.url = "https://example.com/a"
    fake.headers = {"content-type": "text/html"}
    fake.text = "<html><body><article><p>Opened page body about Jev.</p></article></body></html>"

    with patch("page_fetch.httpx.get", return_value=fake):
        rows = enrich_results_with_pages(
            [{"title": "A", "url": "https://example.com/a", "snippet": "snip"}]
        )
    assert rows[0]["content"].startswith("Opened page body")
    assert rows[0]["page"]["ok"] is True


def test_fetch_blocks_localhost():
    page = fetch_url_sync("http://127.0.0.1:8001/health")
    assert page["ok"] is False
    assert page["error"] == "url not allowed"
