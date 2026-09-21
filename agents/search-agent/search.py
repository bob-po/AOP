"""Multi-backend web search with graceful fallbacks (Phase 16)."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

USER_AGENT = "AOP-SearchAgent/0.2 (+https://github.com/aop)"


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _unwrap_ddg_href(href: str) -> str:
    """DuckDuckGo lite wraps targets as /l/?uddg=<url>."""
    try:
        parsed = urlparse(href)
        if "uddg" in parse_qs(parsed.query):
            return unquote(parse_qs(parsed.query)["uddg"][0])
        if href.startswith("//"):
            return "https:" + href
        return href
    except Exception:  # noqa: BLE001
        return href


def _parse_bing(html: str, limit: int = 5) -> list[dict[str, Any]]:
    """Parse Bing SERP HTML into {title, url, snippet} results."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
    except Exception:  # noqa: BLE001
        return []

    results: list[dict[str, Any]] = []
    for li in soup.select("li.b_algo"):
        a = li.select_one("h2 a")
        if not a:
            continue
        url = (a.get("href") or "").strip()
        title = a.get_text(" ", strip=True)
        if not title or not url:
            continue
        p = li.select_one("p")
        snippet = p.get_text(" ", strip=True) if p else ""
        results.append({"title": title, "url": url, "snippet": snippet[:400]})
        if len(results) >= limit:
            break
    return results


async def bing_search(query: str, *, limit: int = 5) -> list[dict[str, Any]] | None:
    """Bing web search — reachable from China, unlike DDG/Wikipedia."""
    endpoint = (
        os.getenv("SEARCH_BING_ENDPOINT", "https://cn.bing.com/search").strip()
        or "https://cn.bing.com/search"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                endpoint,
                params={"q": query, "count": str(max(1, min(limit, 30)))},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            if resp.status_code != 200:
                return None
            html = resp.text
    except Exception:  # noqa: BLE001
        return None

    results = _parse_bing(html, limit=limit)
    return results or None


def mock_results(query: str) -> list[dict[str, Any]]:
    q = quote_plus(query)
    return [
        {
            "title": f"Overview: {query}",
            "url": f"https://example.com/search?q={q}",
            "snippet": f"High-level introduction and references related to '{query}'.",
        },
        {
            "title": f"{query} — best practices",
            "url": "https://example.com/best-practices",
            "snippet": "Practical patterns for planning, routing, and executing multi-agent workflows.",
        },
        {
            "title": f"{query} — architecture notes",
            "url": "https://example.com/architecture",
            "snippet": "Registry, planner, router, scheduler, and A2A executor responsibilities.",
        },
    ]


async def duckduckgo_instant(query: str, *, limit: int = 5) -> list[dict[str, Any]] | None:
    """DuckDuckGo Instant Answer JSON API (no HTML scraping)."""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:  # noqa: BLE001
        return None

    results: list[dict[str, Any]] = []
    abstract = (data.get("AbstractText") or "").strip()
    abstract_url = (data.get("AbstractURL") or "").strip()
    heading = (data.get("Heading") or query).strip()
    if abstract and abstract_url:
        results.append({"title": heading, "url": abstract_url, "snippet": abstract[:400]})

    for topic in data.get("RelatedTopics") or []:
        if len(results) >= limit:
            break
        if isinstance(topic, dict) and "Topics" in topic:
            for sub in topic.get("Topics") or []:
                if len(results) >= limit:
                    break
                text = (sub.get("Text") or "").strip()
                url = (sub.get("FirstURL") or "").strip()
                if text and url:
                    results.append({"title": text.split(" - ")[0][:120], "url": url, "snippet": text[:400]})
        elif isinstance(topic, dict):
            text = (topic.get("Text") or "").strip()
            url = (topic.get("FirstURL") or "").strip()
            if text and url:
                results.append({"title": text.split(" - ")[0][:120], "url": url, "snippet": text[:400]})

    return results or None


async def duckduckgo_lite(query: str, *, limit: int = 5) -> list[dict[str, Any]] | None:
    """Best-effort HTML lite search."""
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                return None
            html = resp.text
    except Exception:  # noqa: BLE001
        return None

    anchors = re.findall(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    snippets = re.findall(
        r'class="result__snippet[^"]*"[^>]*>(.*?)</(?:a|td|div)>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    results: list[dict[str, Any]] = []
    for i, (href, title_html) in enumerate(anchors[:limit]):
        snippet = _strip_tags(snippets[i]) if i < len(snippets) else ""
        results.append(
            {
                "title": _strip_tags(title_html) or query,
                "url": _unwrap_ddg_href(href),
                "snippet": snippet,
            }
        )
    return results or None


async def wikipedia_opensearch(query: str, *, limit: int = 5, lang: str = "en") -> list[dict[str, Any]] | None:
    """Wikipedia OpenSearch — stable public API, good offline-dev fallback when DDG is blocked."""
    lang = (os.getenv("SEARCH_WIKI_LANG") or lang).strip() or "en"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": str(limit),
                    "namespace": "0",
                    "format": "json",
                },
                headers={"User-Agent": USER_AGENT},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:  # noqa: BLE001
        return None

    if not isinstance(data, list) or len(data) < 4:
        return None
    titles, descs, urls = data[1], data[2], data[3]
    results: list[dict[str, Any]] = []
    for i, title in enumerate(titles):
        results.append(
            {
                "title": title,
                "url": urls[i] if i < len(urls) else "",
                "snippet": descs[i] if i < len(descs) else "",
            }
        )
    return results or None


async def run_search(query: str) -> dict[str, Any]:
    mode = (os.getenv("SEARCH_MODE") or "auto").strip().lower()
    limit = int(os.getenv("SEARCH_LIMIT") or "5")
    results: list[dict[str, Any]]
    source = "mock"
    tried: list[str] = []

    if mode == "mock":
        results = mock_results(query)
        source = "mock"
    else:
        backends = [
            ("bing", bing_search),
            ("duckduckgo-instant", duckduckgo_instant),
            ("duckduckgo-lite", duckduckgo_lite),
            ("wikipedia", wikipedia_opensearch),
        ]
        if mode == "live":
            # Prefer live web backends only; still fall back to mock if all fail.
            pass
        elif mode == "wiki":
            backends = [("wikipedia", wikipedia_opensearch)]

        results = []
        for name, fn in backends:
            tried.append(name)
            live = await fn(query, limit=limit)
            if live:
                results = live
                source = name
                break
        if not results:
            results = mock_results(query)
            source = "mock-fallback"

    summary_lines = [f"Search results for: {query}", f"Source: {source}", ""]
    if tried and source.startswith("mock"):
        summary_lines.append(f"(tried: {', '.join(tried)})")
        summary_lines.append("")
    for i, item in enumerate(results, 1):
        summary_lines.append(f"{i}. {item['title']}")
        summary_lines.append(f"   {item['url']}")
        if item.get("snippet"):
            summary_lines.append(f"   {item['snippet']}")
        summary_lines.append("")

    return {
        "query": query,
        "source": source,
        "results": results,
        "tried": tried,
        "summary": "\n".join(summary_lines).strip(),
    }
