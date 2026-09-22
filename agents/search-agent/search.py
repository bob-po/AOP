"""Multi-backend web search with graceful fallbacks (Phase 16)."""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx

from page_fetch import enrich_results_with_pages, format_page_summary

try:
    from deerflow_client import deerflow_search
except ImportError:  # pragma: no cover
    deerflow_search = None  # type: ignore[assignment]

USER_AGENT = "AOP-SearchAgent/0.5 (+https://github.com/aop)"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TECH_TOKEN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9+./_-]{1,})\b")
_STOP_TOKENS = {
    "is",
    "the",
    "a",
    "an",
    "to",
    "of",
    "and",
    "or",
    "in",
    "on",
    "for",
    "what",
    "how",
}


def search_query_variants(query: str) -> list[str]:
    """Prefer English/tech-token queries when Bing/Wiki mishandle Chinese prose.

    cn.bing.com often returns single-character dictionary hits for Chinese
    questions; Wikipedia "A2A" alone hits the Italian utility. Add protocol /
    Agent2Agent disambiguators when present in an agent context.
    """
    q = (query or "").strip()
    if not q:
        return []
    variants: list[str] = []
    tokens = [
        t
        for t in _TECH_TOKEN_RE.findall(q)
        if len(t) >= 2 and t.lower() not in _STOP_TOKENS
    ]
    seen: set[str] = set()
    uniq: list[str] = []
    for t in tokens:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)

    q_lower = q.lower()
    agentish = bool(
        re.search(r"agent|协议|協議|protocol|编排|orchestr", q_lower, flags=re.I)
        or _CJK_RE.search(q)
    )
    if any(t.upper() == "A2A" for t in uniq) and agentish:
        variants.extend(
            [
                "What is A2A Agent2Agent protocol",
                "A2A Agent2Agent open protocol Google",
                "Agent2Agent A2A protocol",
            ]
        )

    if _CJK_RE.search(q) and uniq:
        eng = " ".join(uniq)
        if "protocol" not in eng.lower() and any(t.upper() == "A2A" for t in uniq):
            eng = f"{eng} protocol"
        if not eng.lower().startswith("what"):
            eng = f"What is {eng}"
        variants.append(eng)
        variants.append(" ".join(uniq))

    # "A2A" alone is too ambiguous for Wikipedia — drop bare token variants.
    variants.append(q)
    out: list[str] = []
    seen_q: set[str] = set()
    for v in variants:
        if v.strip().upper() == "A2A":
            continue
        key = v.casefold()
        if key in seen_q:
            continue
        seen_q.add(key)
        out.append(v)
    return out


def _results_relevant(query: str, results: list[dict[str, Any]]) -> bool:
    """Reject SERP junk (dictionary pages, unrelated A2A company hits, etc.)."""
    if not results:
        return False
    ascii_tokens = {
        t.lower()
        for t in _TECH_TOKEN_RE.findall(query)
        if len(t) >= 2 and t.lower() not in _STOP_TOKENS
    }
    q_lower = query.lower()
    want_a2a_protocol = ("a2a" in ascii_tokens) and bool(
        re.search(r"protocol|协议|協議|agent2agent|agent|编排|orchestr", q_lower, flags=re.I)
        or _CJK_RE.search(query)
    )

    hits = 0
    for item in results:
        blob = f"{item.get('title', '')} {item.get('url', '')} {item.get('snippet', '')}".lower()
        if want_a2a_protocol:
            # Must look like Agent2Agent protocol — bare "A2A" wiki/company hits fail.
            if "agent2agent" in blob or ("a2a" in blob and "protocol" in blob):
                hits += 1
            continue
        if ascii_tokens and any(tok in blob for tok in ascii_tokens):
            hits += 1
        elif not ascii_tokens:
            hits += 1
    if want_a2a_protocol:
        return hits >= 1
    need = max(1, (len(results) + 2) // 3)
    return hits >= need


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
    """Bing web search — try English-biased variants when query contains CJK."""
    endpoint = (
        os.getenv("SEARCH_BING_ENDPOINT", "https://cn.bing.com/search").strip()
        or "https://cn.bing.com/search"
    )
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    for variant in search_query_variants(query):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(
                    endpoint,
                    params={"q": variant, "count": str(max(1, min(limit, 30)))},
                    headers=headers,
                )
                if resp.status_code != 200:
                    continue
                results = _parse_bing(resp.text, limit=limit)
        except Exception:  # noqa: BLE001
            continue
        if results and _results_relevant(query, results):
            return results
    return None


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
    """Wikipedia OpenSearch — try English-biased variants for CJK tech questions."""
    lang = (os.getenv("SEARCH_WIKI_LANG") or lang).strip() or "en"
    for variant in search_query_variants(query):
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(
                    f"https://{lang}.wikipedia.org/w/api.php",
                    params={
                        "action": "opensearch",
                        "search": variant,
                        "limit": str(limit),
                        "namespace": "0",
                        "format": "json",
                    },
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
        except Exception:  # noqa: BLE001
            continue

        if not isinstance(data, list) or len(data) < 4:
            continue
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
        if results and _results_relevant(query, results):
            return results
    return None


async def run_search(query: str) -> dict[str, Any]:
    mode = (os.getenv("SEARCH_MODE") or "auto").strip().lower()
    limit = int(os.getenv("SEARCH_LIMIT") or "5")
    results: list[dict[str, Any]]
    source = "mock"
    tried: list[str] = []
    answer = ""

    # DeerFlow deep-research backend (optional). Preferred when configured.
    deerflow_url = (os.getenv("DEERFLOW_URL") or "").strip()
    want_deerflow = mode in ("auto", "live", "deerflow") and bool(deerflow_url)
    if want_deerflow and deerflow_search is not None:
        tried.append("deerflow")
        payload = await deerflow_search(query, limit=limit)
        if payload and (payload.get("results") or payload.get("answer")):
            return payload
        # Keep failure reason visible in later mock/live fallbacks.
        try:
            from deerflow_client import last_error as _deerflow_last_error

            err = _deerflow_last_error()
            if err:
                tried.append(f"deerflow-error:{err[:120]}")
        except Exception:  # noqa: BLE001
            pass
        if mode == "deerflow":
            results = mock_results(query)
            return {
                "query": query,
                "source": "mock-fallback",
                "results": results,
                "tried": tried,
                "summary": (
                    f"Search results for: {query}\nSource: mock-fallback\n\n"
                    f"(tried: {', '.join(tried)})\n\n"
                    + "\n".join(
                        f"{i}. {item['title']}\n   {item['url']}\n   {item.get('snippet', '')}"
                        for i, item in enumerate(results, 1)
                    )
                ).strip(),
            }

    if mode == "mock":
        results = mock_results(query)
        source = "mock"
    elif mode == "deerflow" and not deerflow_url:
        # Explicit deerflow mode without URL → mock fallback
        results = mock_results(query)
        source = "mock-fallback"
        tried.append("deerflow")
    else:
        backends = [
            ("wikipedia", wikipedia_opensearch),
            ("bing", bing_search),
            ("duckduckgo-instant", duckduckgo_instant),
            ("duckduckgo-lite", duckduckgo_lite),
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
            if not live:
                continue
            if not _results_relevant(query, live):
                continue
            results = live
            source = name
            break
        if not results:
            results = mock_results(query)
            source = "mock-fallback"

    if source != "mock" and not source.startswith("mock"):
        results = enrich_results_with_pages(results)

    summary_lines = [f"Search results for: {query}", f"Source: {source}", ""]
    if answer:
        summary_lines.append(answer)
        summary_lines.append("")
    if tried and source.startswith("mock"):
        summary_lines.append(f"(tried: {', '.join(tried)})")
        summary_lines.append("")
    for i, item in enumerate(results, 1):
        summary_lines.append(f"{i}. {item['title']}")
        summary_lines.append(f"   {item['url']}")
        if item.get("snippet"):
            summary_lines.append(f"   {item['snippet']}")
        if item.get("content"):
            summary_lines.append(f"   [page] {item['content'][:500]}")
        summary_lines.append("")
    page_lines = format_page_summary(results)
    if page_lines:
        summary_lines.append("---")
        summary_lines.append("")
        summary_lines.extend(page_lines)

    out: dict[str, Any] = {
        "query": query,
        "source": source,
        "results": results,
        "tried": tried,
        "summary": "\n".join(summary_lines).strip(),
    }
    if answer:
        out["answer"] = answer
    return out
