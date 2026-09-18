"""Browse backends: stub (default) + optional Playwright Chromium (Phase 29)."""

from __future__ import annotations

import base64
import os
import re
from typing import Any
from urllib.parse import urlparse

_URL_RE = re.compile(r"https?://[^\s]+", re.I)


def extract_url(instruction: str) -> str:
    match = _URL_RE.search(instruction or "")
    return match.group(0) if match else ""


def egress_allowed(url: str) -> bool:
    raw = os.getenv("BROWSER_EGRESS_ALLOWLIST", "").strip()
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    if not raw:
        return True
    allowed = [h.strip().lower() for h in raw.split(",") if h.strip()]
    for pattern in allowed:
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
        if host == pattern:
            return True
    return False


def browser_mode() -> str:
    """auto | playwright | stub"""
    return (os.getenv("BROWSER_MODE", "auto") or "auto").strip().lower()


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401

        return True
    except Exception:
        return False


def resolve_backend() -> str:
    mode = browser_mode()
    if mode == "stub":
        return "stub"
    if mode == "playwright":
        return "playwright" if playwright_available() else "stub"
    # auto
    return "playwright" if playwright_available() else "stub"


def _validate_url(instruction: str) -> tuple[str | None, dict[str, Any] | None]:
    url = extract_url(instruction)
    if not url:
        return None, {
            "ok": False,
            "error": "no http(s) URL found in instruction",
            "instruction": instruction,
            "sandbox": "browser",
        }
    scheme = (urlparse(url).scheme or "").lower()
    if scheme not in {"http", "https"}:
        return None, {"ok": False, "error": f"scheme not allowed: {scheme}", "url": url}
    if not egress_allowed(url):
        return None, {
            "ok": False,
            "error": "egress host not allowlisted",
            "url": url,
            "allowlist": os.getenv("BROWSER_EGRESS_ALLOWLIST", ""),
        }
    return url, None


def browse_stub(url: str) -> dict[str, Any]:
    host = urlparse(url).hostname
    return {
        "ok": True,
        "url": url,
        "host": host,
        "title": f"[stub] {host}",
        "snippet": f"Browser stub visited {url} (Playwright/Chromium not active).",
        "screenshot_b64": None,
        "backend": "stub",
        "sandbox": "browser-stub",
        "seccomp_profile": os.getenv("AOP_SECCOMP_PROFILE", "browser-agent"),
        "note": "Set BROWSER_MODE=playwright and install Chromium for live fetch.",
    }


def browse_playwright(url: str) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    timeout_ms = int(os.getenv("BROWSER_TIMEOUT_MS", "15000"))
    want_shot = os.getenv("BROWSER_SCREENSHOT", "0").lower() in {"1", "true", "yes", "on"}
    max_shot = int(os.getenv("BROWSER_SCREENSHOT_MAX_BYTES", "200000"))

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
            ],
        )
        try:
            page = browser.new_page()
            page.set_default_timeout(timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            title = page.title() or urlparse(url).hostname or url
            # Prefer meta description / first paragraph text
            snippet = page.evaluate(
                """() => {
                  const md = document.querySelector('meta[name="description"]');
                  if (md && md.content) return md.content.slice(0, 500);
                  const p = document.querySelector('p');
                  if (p && p.innerText) return p.innerText.slice(0, 500);
                  return (document.body && document.body.innerText || '').slice(0, 500);
                }"""
            )
            shot_b64 = None
            if want_shot:
                raw = page.screenshot(type="png", full_page=False)
                if len(raw) <= max_shot:
                    shot_b64 = base64.b64encode(raw).decode("ascii")
                else:
                    shot_b64 = None
            return {
                "ok": True,
                "url": url,
                "host": urlparse(url).hostname,
                "title": title,
                "snippet": (snippet or "").strip() or f"Loaded {url}",
                "screenshot_b64": shot_b64,
                "backend": "playwright",
                "sandbox": "browser-chromium",
                "seccomp_profile": os.getenv("AOP_SECCOMP_PROFILE", "browser-agent"),
                "timeout_ms": timeout_ms,
            }
        finally:
            browser.close()


def run_browse(instruction: str) -> dict[str, Any]:
    url, err = _validate_url(instruction)
    if err:
        return err
    assert url is not None
    backend = resolve_backend()
    if backend == "playwright":
        try:
            return browse_playwright(url)
        except Exception as exc:  # noqa: BLE001
            # Soft-fallback so control plane stays available without browser binary
            out = browse_stub(url)
            out["ok"] = True
            out["fallback_error"] = str(exc)
            out["note"] = f"Playwright failed ({exc}); returned stub."
            return out
    return browse_stub(url)
