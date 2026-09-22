"""Sandbox for untrusted report output and PDF rendering.

Model output is treated as data. HTML/SVG are escaped or stripped before they
touch a renderer. PDF conversion runs as a subprocess whose cwd is a temporary
directory containing only the bundle — the model never supplies the command
line, and API keys are not inherited.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_UNSAFE_TAG = re.compile(
    r"<\s*/?\s*(script|iframe|object|embed|base|form)\b[^>]*>",
    re.IGNORECASE,
)
_LINK_TAG = re.compile(r"<\s*link\b[^>]*>", re.IGNORECASE)
_META_TAG = re.compile(r"<\s*meta\b[^>]*>", re.IGNORECASE)
_UNSAFE_ATTR = re.compile(
    r"\s(?:on[a-z]+\s*=|href\s*=\s*[\"']\s*javascript:|src\s*=\s*[\"']\s*javascript:)",
    re.IGNORECASE,
)
_KEEP_ENV = (
    "PATH",
    "SYSTEMROOT",
    "WINDIR",
    "LOCALAPPDATA",
    "APPDATA",
    "USERPROFILE",
    "HOME",
    "TEMP",
    "TMP",
    "LANG",
    "PATHEXT",
)


def sanitize_markup(text: str) -> str:
    """Drop active tags and event-handler attributes. Text content stays.

    A local stylesheet and a charset declaration are part of the report
    document, so they are kept. External stylesheets are removed.
    """
    cleaned = _UNSAFE_TAG.sub("", text or "")

    def keep_link(match: re.Match[str]) -> str:
        tag = match.group(0)
        local = re.search(r"href\s*=\s*['\"]report\.css['\"]", tag, re.IGNORECASE)
        sheet = re.search(r"rel\s*=\s*['\"]stylesheet['\"]", tag, re.IGNORECASE)
        return tag if local and sheet else ""

    def keep_meta(match: re.Match[str]) -> str:
        tag = match.group(0)
        return tag if re.search(r"charset\s*=", tag, re.IGNORECASE) else ""

    cleaned = _LINK_TAG.sub(keep_link, cleaned)
    cleaned = _META_TAG.sub(keep_meta, cleaned)
    cleaned = _UNSAFE_ATTR.sub("", cleaned)
    return cleaned


def _renderer_env(work: Path) -> dict[str, str]:
    env = {key: os.environ[key] for key in _KEEP_ENV if os.environ.get(key)}
    env["TEMP"] = str(work)
    env["TMP"] = str(work)
    return env


def _run(argv: list[str], work: Path, timeout: float) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv,
        cwd=work,
        env=_renderer_env(work),
        timeout=timeout,
        capture_output=True,
        shell=False,
        check=False,
    )


def _which(name: str) -> str | None:
    found = shutil.which(name)
    return found or None


def _browser_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def render_pdf(files: dict[str, str]) -> dict[str, Any]:
    """Render ``report.html`` to PDF inside a temp jail.

    Engine order is controlled by ``REPORT_PDF_ENGINE``: ``auto`` (default),
    ``paged``, ``browser``, or ``none``.
    """
    mode = (os.getenv("REPORT_PDF_ENGINE") or "auto").strip().lower()
    info: dict[str, Any] = {
        "engine": "none",
        "sandbox": "subprocess-workdir",
        "reason": "renderer not requested",
    }
    if mode == "none":
        return info

    timeout = float(os.getenv("REPORT_PDF_TIMEOUT", "45"))
    html = files.get("report.html")
    css = files.get("report.css")
    if not html or not css:
        info["reason"] = "bundle is missing report.html or report.css"
        return info

    with tempfile.TemporaryDirectory(prefix="aop-report-") as tmp:
        work = Path(tmp).resolve()
        _materialize(work, files)
        pdf_path = work / "report.pdf"
        tried: list[str] = []

        if mode in {"auto", "paged"}:
            tried.append("paged")
            binary = os.getenv("REPORT_PAGEDJS_BIN") or _which("pagedjs-cli")
            if binary:
                _run([binary, "report.html", "-o", "report.pdf"], work, timeout)
                if pdf_path.is_file():
                    return _done("paged", pdf_path)
            elif mode == "paged":
                info["reason"] = "pagedjs-cli is not on PATH"
                info["tried"] = tried
                return info

        if mode in {"auto", "browser"}:
            tried.append("browser")
            script = Path(__file__).resolve().parent / "browser_pdf.py"
            if _browser_available() and script.is_file():
                _run([sys.executable, str(script)], work, timeout)
                if pdf_path.is_file():
                    return _done("browser", pdf_path)
            elif mode == "browser":
                info["reason"] = "playwright is not installed"
                info["tried"] = tried
                return info

        info["reason"] = "no pagedjs-cli or playwright runtime"
        info["tried"] = tried
        return info


def _materialize(work: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        rel = name.replace("\\", "/").lstrip("/")
        if ".." in rel.split("/"):
            continue
        dest = (work / rel).resolve()
        if work not in dest.parents and dest != work:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")


def _done(engine: str, pdf_path: Path) -> dict[str, Any]:
    import base64

    raw = pdf_path.read_bytes()
    return {
        "engine": engine,
        "sandbox": "subprocess-workdir",
        "bytes": base64.b64encode(raw).decode("ascii"),
        "size": len(raw),
    }
