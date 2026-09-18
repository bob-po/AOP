"""Unit tests for infrastructure/postgres/migrate.py helpers (no DB required)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MIGRATE_PATH = ROOT / "infrastructure" / "postgres" / "migrate.py"


def _load_migrate():
    spec = importlib.util.spec_from_file_location("aop_migrate", MIGRATE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["aop_migrate"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_split_sql_skips_comments_and_splits():
    m = _load_migrate()
    script = """
-- header
CREATE TABLE a (id INT);

CREATE TABLE b (
  id INT
);
"""
    parts = m.split_sql(script)
    assert len(parts) == 2
    assert "CREATE TABLE a" in parts[0]
    assert "CREATE TABLE b" in parts[1]


def test_list_migrations_includes_init_files():
    m = _load_migrate()
    versions = [v for v, _p, _s in m.list_migrations()]
    assert "000_schema_migrations" in versions
    assert "001_init" in versions
    assert "002_evaluation" in versions
    assert "003_memory" in versions
    assert "004_tenant_memory" in versions
    assert "005_audit_index" in versions
    assert "006_user_auth" in versions
    assert "007_tenant_quotas" in versions
    assert "008_billing_invoices" in versions
    assert "009_billing_checkout" in versions
    assert "010_billing_webhooks" in versions
    assert "011_quota_grants" in versions
    assert "012_tenant_egress" in versions


def test_memory_evaluation_have_no_runtime_ddl():
    memory = (ROOT / "apps" / "orchestrator" / "memory" / "__init__.py").read_text(encoding="utf-8")
    evaluation = (ROOT / "apps" / "orchestrator" / "evaluation" / "__init__.py").read_text(
        encoding="utf-8"
    )
    for src, name in ((memory, "memory"), (evaluation, "evaluation")):
        assert "CREATE TABLE" not in src.upper(), name
        assert "def ensure_schema" not in src, name
