"""Fetch public web pages after search and extract readable text.

Used by web-search (enrich top hits) and the url-fetch skill. Only http(s)
URLs are allowed; loopback and private addresses are rejected.
"""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

USER_AGENT = (
    "Mozilla/5.0 (compatible; AOP-SearchAgent/0.4; +https://github.com/aop)"
)

# Keep in sync with search._SERP_JUNK_HOSTS — never open these as "citations".
_SERP_JUNK_HOSTS = {
    "www.sogou.com",
    "sogou.com",
    "www.baidu.com",
    "baidu.com",
    "cn.bing.com",
    "www.bing.com",
    "bing.com",
    "www.so.com",
    "so.com",
    "www.google.com",
    "www.google.com.hk",
    "google.com",
    "www.17so.cn",
    "17so.cn",
}

_SCRIPT_STYLE = re.compile(
    r"<(script|style|noscript|svg|iframe)[\s\S]*?</\1>",
    re.IGNORECASE,
)
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _max_pages() -> int:
    try:
        return max(0, min(int(os.getenv("SEARCH_FETCH_PAGES", "3")), 8))
    except ValueError:
        return 3


def _max_chars() -> int:
    try:
        return max(400, min(int(os.getenv("SEARCH_FETCH_CHARS", "2500")), 12000))
    except ValueError:
        return 2500


def _timeout() -> float:
    try:
        return max(3.0, min(float(os.getenv("SEARCH_FETCH_TIMEOUT", "10")), 30.0))
    except ValueError:
        return 10.0


def is_public_http_url(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "metadata.google.internal"}:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_global
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        # DNS may fail offline; still allow the request and let httpx decide.
        return True
    for info in infos:
        addr = info[4][0]
        try:
            if not ipaddress.ip_address(addr).is_global:
                return False
        except ValueError:
            continue
    return True


def extract_page_text(html: str, *, limit: int | None = None) -> str:
    limit = limit if limit is not None else _max_chars()
    text = ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "iframe", "nav", "footer", "header"]):
            tag.decompose()
        root = soup.find("article") or soup.find("main") or soup.body or soup
        text = root.get_text("\n", strip=True) if root else ""
    except Exception:  # noqa: BLE001
        cleaned = _SCRIPT_STYLE.sub(" ", html or "")
        text = _TAGS.sub(" ", cleaned)
    text = _WS.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def fetch_url_sync(url: str) -> dict[str, Any]:
    """Fetch one URL in a constrained sandbox (SSRF / size / type limits)."""
    target = (url or "").strip()
    if not is_public_http_url(target):
        return {
            "url": target,
            "ok": False,
            "status": 0,
            "title": "",
            "content": "",
            "error": "url not allowed (sandbox)",
        }
    try:
        with httpx.Client(
            timeout=_timeout(),
            follow_redirects=True,
            max_redirects=5,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,text/plain;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            },
        ) as client:
            resp = client.get(target)
        # Re-validate final URL after redirects (SSRF via redirect).
        final_url = str(resp.url)
        if not is_public_http_url(final_url):
            return {
                "url": final_url,
                "ok": False,
                "status": resp.status_code,
                "title": "",
                "content": "",
                "error": "redirect target not allowed (sandbox)",
            }
        status = resp.status_code
        if status >= 400:
            return {
                "url": final_url,
                "ok": False,
                "status": status,
                "title": "",
                "content": "",
                "error": f"http {status}",
            }
        ctype = (resp.headers.get("content-type") or "").lower()
        if "html" not in ctype and "text/" not in ctype and "xml" not in ctype:
            return {
                "url": final_url,
                "ok": False,
                "status": status,
                "title": "",
                "content": "",
                "error": f"unsupported content-type: {ctype or 'unknown'}",
            }
        # Cap raw body before parsing (sandbox size limit).
        body = resp.text[: min(500_000, _max_chars() * 40)]
        title = ""
        m = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.I | re.S)
        if m:
            title = _WS.sub(" ", _TAGS.sub("", m.group(1))).strip()[:200]
        content = extract_page_text(body)
        return {
            "url": final_url,
            "ok": bool(content),
            "status": status,
            "title": title,
            "content": content,
            "error": "" if content else "empty page text",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "url": target,
            "ok": False,
            "status": 0,
            "title": "",
            "content": "",
            "error": str(exc)[:200],
        }


async def fetch_url(url: str) -> dict[str, Any]:
    """Async wrapper around the sync fetcher (keeps one implementation)."""
    return fetch_url_sync(url)


def enrich_results_with_pages(
    results: list[dict[str, Any]],
    *,
    max_pages: int | None = None,
) -> list[dict[str, Any]]:
    """Visit top search hits and attach page content onto each result dict."""
    n = _max_pages() if max_pages is None else max(0, max_pages)
    if n <= 0 or not results:
        return results
    enriched: list[dict[str, Any]] = []
    fetched = 0
    for item in results:
        row = dict(item)
        host = ""
        try:
            host = (urlparse(str(row.get("url") or "")).hostname or "").lower()
        except Exception:  # noqa: BLE001
            host = ""
        if host in _SERP_JUNK_HOSTS:
            # Never open search-engine homepages / portal shells.
            enriched.append(row)
            continue
        url = str(row.get("url") or "").strip()
        if fetched < n and url and is_public_http_url(url):
            page = fetch_url_sync(url)
            row["page"] = {
                "ok": page["ok"],
                "status": page["status"],
                "title": page.get("title") or "",
                "error": page.get("error") or "",
            }
            if page.get("content"):
                row["content"] = page["content"]
                if not row.get("snippet"):
                    row["snippet"] = page["content"][:400]
            fetched += 1
        enriched.append(row)
    return enriched


def format_page_summary(results: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    opened = [r for r in results if r.get("content")]
    if not opened:
        return lines
    lines.append(f"Opened {len(opened)} page(s):")
    lines.append("")
    for i, item in enumerate(opened, 1):
        lines.append(f"{i}. {item.get('title') or item.get('url')}")
        lines.append(f"   {item.get('url')}")
        content = str(item.get("content") or "")
        if content:
            excerpt = content if len(content) <= 900 else content[:900].rstrip() + "…"
            lines.append(f"   {excerpt}")
        lines.append("")
    return lines
