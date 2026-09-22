"""Trusted Chromium PDF renderer.

Reads ``./report.html`` from the process cwd and writes ``./report.pdf``.
The command line is fixed by the parent sandbox; this file does not accept
model-authored code or URLs.
"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    html = Path("report.html").resolve()
    pdf = Path("report.pdf").resolve()
    cwd = Path.cwd().resolve()
    if html.parent != cwd or pdf.parent != cwd:
        raise SystemExit("refusing to read or write outside the sandbox directory")
    if not html.is_file():
        raise SystemExit("report.html is missing")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(html.as_uri(), wait_until="load")
            page.pdf(path=str(pdf), print_background=True, format="A4")
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
