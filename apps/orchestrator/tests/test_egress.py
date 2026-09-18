"""Phase 34: tenant egress host policy (no DB)."""

from __future__ import annotations

import pytest

from egress import EgressDenied, EgressService, evaluate_url, extract_urls, host_matches


def test_host_matches_wildcard():
    assert host_matches("en.wikipedia.org", "*.wikipedia.org")
    assert host_matches("wikipedia.org", "*.wikipedia.org")
    assert not host_matches("evil.test", "*.wikipedia.org")
    assert host_matches("example.com", "example.com")


def test_evaluate_modes():
    patterns = ["example.com", "*.wikipedia.org"]
    assert evaluate_url("https://example.com/a", mode="open", patterns=[])
    assert evaluate_url("https://example.com/a", mode="allowlist", patterns=patterns)
    assert not evaluate_url("https://evil.test/", mode="allowlist", patterns=patterns)
    assert not evaluate_url("https://evil.test/", mode="denylist", patterns=["evil.test"])
    assert evaluate_url("https://ok.test/", mode="denylist", patterns=["evil.test"])
    assert not evaluate_url("ftp://example.com/", mode="open", patterns=[])


def test_extract_urls():
    assert extract_urls("see https://a.test/x and http://b.test") == [
        "https://a.test/x",
        "http://b.test",
    ]


def test_assert_skips_non_browser(monkeypatch):
    monkeypatch.setenv("TENANT_EGRESS", "1")
    svc = EgressService(database_url="postgresql://invalid")
    svc.assert_query_allowed("https://evil.test", skill="web-search")


def test_assert_denies_with_stub_policy(monkeypatch):
    monkeypatch.setenv("TENANT_EGRESS", "1")
    svc = EgressService(database_url="postgresql://invalid")
    policy = {
        "enabled": True,
        "mode": "allowlist",
        "pattern_list": ["example.com"],
        "patterns": "example.com",
    }
    monkeypatch.setattr(svc, "get", lambda tenant_id=None: policy)
    with pytest.raises(EgressDenied, match="denied"):
        svc.assert_query_allowed(
            "open https://evil.test/page",
            skill="browser-automation",
        )
    svc.assert_query_allowed(
        "open https://example.com/ok",
        skill="browser-automation",
    )
