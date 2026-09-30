"""Unit tests for harness profile single source of truth."""

from __future__ import annotations

from agent_runtime.harness.profiles import (
    HARNESS_PROFILES,
    as_port_tuples,
    default_ports,
    host_port_map,
    marketplace_catalog_rows,
    profile_by_key,
)


def test_five_unified_profiles() -> None:
    keys = [p.key for p in HARNESS_PROFILES]
    assert keys == [
        "claude-code",
        "deepseek-harness",
        "pi",
        "openclaw",
        "hermes",
    ]


def test_ports_unique_and_stable() -> None:
    ports = default_ports()
    assert ports == {
        "claude-code": 8011,
        "deepseek-harness": 8012,
        "pi": 8013,
        "openclaw": 8014,
        "hermes": 8015,
    }
    assert len(set(ports.values())) == len(ports)


def test_host_port_map_includes_harness_alias() -> None:
    m = host_port_map()
    assert m["harness-agent"] == 8011
    assert m["claude-code"] == 8011


def test_as_port_tuples_order() -> None:
    assert as_port_tuples()[0] == ("claude-code", 8011)
    assert as_port_tuples()[-1] == ("hermes", 8015)


def test_profile_by_key() -> None:
    assert profile_by_key("PI") is not None
    assert profile_by_key("PI").port == 8013
    assert profile_by_key("missing") is None


def test_marketplace_catalog_rows() -> None:
    rows = marketplace_catalog_rows(
        endpoint_resolver=lambda _k, fb: fb,
    )
    assert len(rows) == 5
    assert all(r["skills"] == [] for r in rows)
    assert rows[0]["package_id"] == "pkg-claude-code"
    assert rows[0]["default_endpoint"] == "http://127.0.0.1:8011"


def test_aop_node_plugin_toml_ports_match_profiles() -> None:
    """L04: keep plugins/*/plugin.toml health_url ports in sync with HARNESS_PROFILES."""
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parents[3]
    plugins = repo / "apps" / "client" / "aop-node" / "plugins"
    assert plugins.is_dir(), plugins
    ports = default_ports()
    health_re = re.compile(r'health_url\s*=\s*"http://127\.0\.0\.1:(\d+)/health"')
    for key, expected_port in ports.items():
        toml = plugins / key / "plugin.toml"
        assert toml.is_file(), f"missing plugin.toml for profile {key}: {toml}"
        text = toml.read_text(encoding="utf-8")
        m = health_re.search(text)
        assert m, f"{toml} missing health_url with localhost port"
        assert int(m.group(1)) == expected_port, (
            f"{key}: plugin.toml port {m.group(1)} != profiles.py {expected_port}"
        )
