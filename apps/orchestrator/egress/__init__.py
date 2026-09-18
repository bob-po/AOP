"""Tenant egress (outbound URL) policy (Phase 34)."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Skills whose user input may contain outbound URLs to gate
EGRESS_SKILLS: frozenset[str] = frozenset({"browser-automation"})

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


class EgressDenied(PermissionError):
    def __init__(self, message: str, *, url: str | None = None, policy: dict[str, Any] | None = None):
        super().__init__(message)
        self.url = url
        self.policy = policy or {}


def egress_enforcement() -> bool:
    return os.getenv("TENANT_EGRESS", "1").lower() not in {"0", "false", "no", "off"}


def host_matches(host: str, pattern: str) -> bool:
    host = (host or "").lower().strip("[]")
    pattern = (pattern or "").lower().strip()
    if not host or not pattern:
        return False
    if pattern.startswith("*."):
        suffix = pattern[1:]  # .example.com
        return host == pattern[2:] or host.endswith(suffix)
    return host == pattern


def parse_patterns(raw: str) -> list[str]:
    return [p.strip().lower() for p in (raw or "").split(",") if p.strip()]


def extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text or "")


def evaluate_host(host: str, *, mode: str, patterns: list[str]) -> bool:
    """Return True if host is allowed under policy."""
    mode = (mode or "open").lower()
    host = (host or "").lower().strip("[]")
    if not host:
        return False
    if mode == "open":
        return True
    if mode == "allowlist":
        if not patterns:
            return False
        return any(host_matches(host, p) for p in patterns)
    if mode == "denylist":
        if not patterns:
            return True
        return not any(host_matches(host, p) for p in patterns)
    return False


def evaluate_url(url: str, *, mode: str, patterns: list[str]) -> bool:
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        return False
    return evaluate_host(parsed.hostname or "", mode=mode, patterns=patterns)


class EgressService:
    def __init__(
        self,
        database_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.tenant_id = tenant_id

    def get(self, *, tenant_id: str | None = None) -> dict[str, Any]:
        tid = tenant_id or self.tenant_id
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            row = conn.execute(
                """
                SELECT tenant_id::text, mode, patterns, enabled, updated_at
                FROM tenant_egress_policies
                WHERE tenant_id = %s::uuid
                """,
                (tid,),
            ).fetchone()
        if not row:
            return {
                "tenant_id": tid,
                "mode": "open",
                "patterns": "",
                "pattern_list": [],
                "enabled": True,
                "exists": False,
                "updated_at": None,
                "enforcement": egress_enforcement(),
            }
        out = dict(row)
        out["exists"] = True
        out["pattern_list"] = parse_patterns(out.get("patterns") or "")
        out["enforcement"] = egress_enforcement()
        if out.get("updated_at") is not None:
            out["updated_at"] = out["updated_at"].isoformat()
        return out

    def upsert(
        self,
        *,
        tenant_id: str | None = None,
        mode: str | None = None,
        patterns: str | None = None,
        enabled: bool | None = None,
    ) -> dict[str, Any]:
        tid = tenant_id or self.tenant_id
        current = self.get(tenant_id=tid)
        new_mode = (mode or current.get("mode") or "open").lower()
        if new_mode not in {"open", "allowlist", "denylist"}:
            raise ValueError(f"invalid mode: {new_mode}")
        new_patterns = patterns if patterns is not None else (current.get("patterns") or "")
        new_enabled = bool(enabled if enabled is not None else current.get("enabled", True))

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            conn.execute(
                """
                INSERT INTO tenant_egress_policies (tenant_id, mode, patterns, enabled, updated_at)
                VALUES (%s::uuid, %s, %s, %s, now())
                ON CONFLICT (tenant_id) DO UPDATE SET
                  mode = EXCLUDED.mode,
                  patterns = EXCLUDED.patterns,
                  enabled = EXCLUDED.enabled,
                  updated_at = now()
                """,
                (tid, new_mode, new_patterns, new_enabled),
            )
            conn.commit()
        return self.get(tenant_id=tid)

    def check_url(self, url: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        policy = self.get(tenant_id=tenant_id)
        allowed = True
        reason = "enforcement_off"
        if egress_enforcement() and policy.get("enabled", True):
            allowed = evaluate_url(
                url,
                mode=str(policy.get("mode") or "open"),
                patterns=list(policy.get("pattern_list") or []),
            )
            reason = "allowed" if allowed else "denied_by_policy"
        return {
            "url": url,
            "host": urlparse(url).hostname,
            "allowed": allowed,
            "reason": reason,
            "policy": {
                "mode": policy.get("mode"),
                "patterns": policy.get("patterns"),
                "enabled": policy.get("enabled"),
            },
            "as_of": datetime.now(timezone.utc).isoformat(),
        }

    def assert_query_allowed(
        self,
        query: str,
        *,
        skill: str | None = None,
        tenant_id: str | None = None,
    ) -> None:
        if not egress_enforcement():
            return
        skill = (skill or "").strip()
        if skill and skill not in EGRESS_SKILLS:
            return
        # If skill unknown but URLs present and skill is egress-related — still check when skill in set
        if skill not in EGRESS_SKILLS:
            return
        policy = self.get(tenant_id=tenant_id)
        if not policy.get("enabled", True):
            return
        urls = extract_urls(query)
        if not urls:
            return
        mode = str(policy.get("mode") or "open")
        patterns = list(policy.get("pattern_list") or [])
        for url in urls:
            if not evaluate_url(url, mode=mode, patterns=patterns):
                raise EgressDenied(
                    f"egress denied for {url} under mode={mode}",
                    url=url,
                    policy=policy,
                )

    def allowlist_csv(self, *, tenant_id: str | None = None) -> str:
        """CSV suitable for BROWSER_EGRESS_ALLOWLIST when mode=allowlist."""
        policy = self.get(tenant_id=tenant_id)
        if policy.get("mode") == "allowlist":
            return str(policy.get("patterns") or "")
        return ""
