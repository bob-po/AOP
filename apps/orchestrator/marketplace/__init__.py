"""Agent Marketplace catalog + install helpers."""

from __future__ import annotations

import os
from typing import Any

import httpx
import psycopg
from psycopg.rows import dict_row
from db import connect

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _agent_endpoint(env_key: str, fallback: str) -> str:
    return (os.getenv(env_key) or fallback).rstrip("/")


# Curated catalog for local/dev marketplace. Install uses endpoint registration.
# In Docker, set AOP_AGENT_*_URL to service DNS (e.g. http://search-agent:8001).
CATALOG: list[dict[str, Any]] = [
    {
        "package_id": "pkg-search",
        "name": "Search Agent",
        "description": "Multi-backend web search (DDG / Wikipedia) with mock fallback",
        "publisher": "AOP Official",
        "version": "0.2.0",
        "skills": ["web-search"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_SEARCH_URL", "http://127.0.0.1:8001"),
        "agent_key": "search-agent",
        "tags": ["research", "search"],
    },
    {
        "package_id": "pkg-rag",
        "name": "RAG Agent",
        "description": "Hybrid TF-IDF vector RAG with citations over local corpus",
        "publisher": "AOP Official",
        "version": "0.3.0",
        "skills": ["knowledge-search", "qa"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_RAG_URL", "http://127.0.0.1:8002"),
        "agent_key": "rag-agent",
        "tags": ["rag", "knowledge"],
    },
    {
        "package_id": "pkg-report",
        "name": "Report Agent",
        "description": "Generate markdown reports from upstream research",
        "publisher": "AOP Official",
        "version": "0.2.0",
        "skills": ["report-generation"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_REPORT_URL", "http://127.0.0.1:8003"),
        "agent_key": "report-agent",
        "tags": ["report", "writing"],
    },
    {
        "package_id": "pkg-analysis",
        "name": "Analysis Agent",
        "description": "Business analysis synthesizer for research DAGs",
        "publisher": "AOP Official",
        "version": "0.1.0",
        "skills": ["business-analysis"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_ANALYSIS_URL", "http://127.0.0.1:8004"),
        "agent_key": "analysis-agent",
        "tags": ["analysis", "business"],
    },
    {
        "package_id": "pkg-image",
        "name": "Image Agent",
        "description": "Text-to-image stub (ComfyUI-shaped)",
        "publisher": "AOP Official",
        "version": "0.1.0",
        "skills": ["text-to-image"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_IMAGE_URL", "http://127.0.0.1:8005"),
        "agent_key": "image-agent",
        "tags": ["image", "media"],
    },
    {
        "package_id": "pkg-video",
        "name": "Video Agent",
        "description": "Text-to-video stub (AIVE-shaped)",
        "publisher": "AOP Official",
        "version": "0.1.0",
        "skills": ["text-to-video"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_VIDEO_URL", "http://127.0.0.1:8006"),
        "agent_key": "video-agent",
        "tags": ["video", "media"],
    },
    {
        "package_id": "pkg-code",
        "name": "Code Agent",
        "description": "AST-safe code execution under seccomp / no-new-privileges",
        "publisher": "AOP Official",
        "version": "0.1.0",
        "skills": ["code-execution"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_CODE_URL", "http://127.0.0.1:8007"),
        "agent_key": "code-agent",
        "tags": ["code", "sandbox", "high-risk"],
    },
    {
        "package_id": "pkg-browser",
        "name": "Browser Agent",
        "description": "Browser automation with Playwright Chromium (stub fallback)",
        "publisher": "AOP Official",
        "version": "0.2.0",
        "skills": ["browser-automation"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_BROWSER_URL", "http://127.0.0.1:8008"),
        "agent_key": "browser-agent",
        "tags": ["browser", "sandbox", "high-risk", "chromium"],
    },
    {
        "package_id": "pkg-ppt",
        "name": "PPT Agent",
        "description": "PowerPoint decks via DeepPresenter (PPTAgent) with python-pptx stub",
        "publisher": "AOP Official",
        "version": "0.1.0",
        "skills": ["ppt-generation"],
        "default_endpoint": _agent_endpoint("AOP_AGENT_PPT_URL", "http://127.0.0.1:8009"),
        "agent_key": "ppt-agent",
        "tags": ["ppt", "presentation", "pptagent"],
    },
]


class MarketplaceService:
    def __init__(
        self,
        database_url: str | None = None,
        gateway_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.gateway_url = (gateway_url or os.getenv("GATEWAY_URL", "http://127.0.0.1:8080")).rstrip(
            "/"
        )
        self.tenant_id = tenant_id

    def catalog(self, *, q: str | None = None) -> list[dict[str, Any]]:
        installed = self._installed_by_key()
        query = (q or "").strip().lower()
        out: list[dict[str, Any]] = []
        for pkg in CATALOG:
            if query:
                hay = " ".join(
                    [
                        pkg["name"],
                        pkg["description"],
                        pkg["agent_key"],
                        " ".join(pkg.get("skills") or []),
                        " ".join(pkg.get("tags") or []),
                    ]
                ).lower()
                if query not in hay:
                    continue
            agent = installed.get(pkg["agent_key"])
            item = {
                **pkg,
                "installed": agent is not None,
                "agent": agent,
            }
            out.append(item)
        return out

    def install(
        self,
        *,
        package_id: str | None = None,
        endpoint: str | None = None,
    ) -> dict[str, Any]:
        ep = (endpoint or "").strip()
        if package_id and not ep:
            pkg = next((p for p in CATALOG if p["package_id"] == package_id), None)
            if not pkg:
                raise ValueError(f"package not found: {package_id}")
            ep = pkg["default_endpoint"]
        if not ep:
            raise ValueError("package_id or endpoint is required")

        resp = httpx.post(
            f"{self.gateway_url}/v1/agents/register",
            json={"endpoint": ep},
            timeout=30.0,
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"install failed: {resp.status_code} {resp.text}")
        data = resp.json()
        return {
            "installed": True,
            "endpoint": ep,
            "package_id": package_id,
            "agent": data,
        }

    def _installed_by_key(self) -> dict[str, dict[str, Any]]:
        sql = """
            SELECT a.id::text AS agent_id, a.agent_key, a.name, a.status,
                   a.current_version AS version,
                   COALESCE((
                     SELECT e.url FROM agent_endpoints e
                     WHERE e.agent_id = a.id AND e.is_primary = true
                     ORDER BY e.updated_at DESC LIMIT 1
                   ), '') AS endpoint,
                   COALESCE((
                     SELECT array_agg(s.skill_id ORDER BY s.skill_id)
                     FROM agent_skills s WHERE s.agent_id = a.id
                   ), '{}') AS skills
            FROM agents a
            WHERE a.tenant_id = %s::uuid
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (self.tenant_id,)).fetchall()
        return {r["agent_key"]: dict(r) for r in rows}
