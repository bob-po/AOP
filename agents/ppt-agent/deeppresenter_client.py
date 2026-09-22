"""DeepPresenter (PPTAgent v1.1.38) backend client.

Prefer HTTP ``PPTAGENT_GENERATE_URL`` when a thin generate API is exposed.
Otherwise ``docker exec`` into ``PPTAGENT_CONTAINER`` and run ``pptagent generate``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import httpx

_LAST_ERROR = ""


def last_error() -> str:
    return _LAST_ERROR


def _set_error(msg: str) -> None:
    global _LAST_ERROR
    _LAST_ERROR = (msg or "")[:500]


def _timeout() -> float:
    try:
        return float(os.getenv("PPTAGENT_TIMEOUT") or "600")
    except ValueError:
        return 600.0


def _container() -> str:
    return (os.getenv("PPTAGENT_CONTAINER") or "aop-deeppresenter").strip()


def _generate_url() -> str:
    return (os.getenv("PPTAGENT_GENERATE_URL") or "").strip().rstrip("/")


def _http_generate(query: str) -> tuple[bytes, dict[str, Any]] | None:
    base = _generate_url()
    if not base:
        return None
    url = f"{base}/generate" if not base.endswith("/generate") else base
    try:
        with httpx.Client(timeout=_timeout()) as client:
            r = client.post(url, json={"instruction": query, "prompt": query})
            if r.status_code >= 400:
                _set_error(f"HTTP {r.status_code}: {r.text[:200]}")
                return None
            ctype = (r.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                data = r.json()
                if isinstance(data, dict) and data.get("pptx_base64"):
                    import base64

                    raw = base64.b64decode(data["pptx_base64"])
                    return raw, {
                        "source": "deeppresenter-http",
                        "slide_count": data.get("slide_count"),
                        "format": "pptx",
                        "note": "DeepPresenter HTTP generate",
                    }
                _set_error("HTTP JSON missing pptx_base64")
                return None
            if r.content[:2] == b"PK":
                return r.content, {
                    "source": "deeppresenter-http",
                    "format": "pptx",
                    "note": "DeepPresenter HTTP generate (binary)",
                }
            _set_error("HTTP response is not pptx")
            return None
    except Exception as exc:  # noqa: BLE001
        _set_error(f"HTTP generate failed: {exc}")
        return None


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _docker_exec_generate(query: str) -> tuple[bytes, dict[str, Any]] | None:
    if not _docker_available():
        _set_error("docker not on PATH")
        return None
    name = _container()
    # Probe container
    probe = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if probe.returncode != 0 or "true" not in (probe.stdout or "").lower():
        _set_error(f"container {name} not running")
        return None

    out_name = f"aop-{uuid.uuid4().hex[:10]}.pptx"
    remote_path = f"/opt/workspace/{out_name}"
    cmd = [
        "docker",
        "exec",
        name,
        "pptagent",
        "generate",
        query,
        "-o",
        remote_path,
    ]
    try:
        gen = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_timeout(),
        )
        if gen.returncode != 0:
            _set_error(
                f"pptagent generate exit {gen.returncode}: {(gen.stderr or gen.stdout or '')[:300]}"
            )
            return None
    except subprocess.TimeoutExpired:
        _set_error("pptagent generate timed out")
        return None
    except Exception as exc:  # noqa: BLE001
        _set_error(f"docker exec failed: {exc}")
        return None

    with tempfile.TemporaryDirectory(prefix="aop-ppt-") as td:
        local = Path(td) / out_name
        cp = subprocess.run(
            ["docker", "cp", f"{name}:{remote_path}", str(local)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if cp.returncode != 0 or not local.is_file():
            _set_error(f"docker cp failed: {(cp.stderr or '')[:200]}")
            return None
        raw = local.read_bytes()
        if raw[:2] != b"PK":
            _set_error("copied file is not a pptx zip")
            return None
        # best-effort cleanup in container
        subprocess.run(
            ["docker", "exec", name, "rm", "-f", remote_path],
            capture_output=True,
            timeout=15,
        )
        return raw, {
            "source": "deeppresenter-docker",
            "format": "pptx",
            "container": name,
            "note": "DeepPresenter via docker exec pptagent generate",
        }


def deeppresenter_generate(query: str) -> tuple[bytes, dict[str, Any]] | None:
    """Return (pptx_bytes, meta) or None on failure."""
    _set_error("")
    q = (query or "").strip()
    if not q:
        _set_error("empty query")
        return None

    http_result = _http_generate(q)
    if http_result is not None:
        return http_result

    return _docker_exec_generate(q)
