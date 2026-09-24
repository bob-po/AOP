"""Phase 5.12 — HTTP tenant isolation helpers (hermetic via TestClient when possible)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

# Force memory before importing main
import os

os.environ.setdefault("EXECUTION_STORE", "memory")
os.environ.setdefault("EXECUTION_OUTBOX_ENABLED", "false")
os.environ.setdefault("EXECUTION_RECOVERY_ENABLED", "false")


@pytest.fixture(scope="module")
def client():
    # Import after env is set; StreamClient may still need redis — skip if unavailable
    try:
        import main as orch_main

        return TestClient(orch_main.app)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"orchestrator main import failed (deps): {exc}")


def test_tenant_forbidden_on_other_tenant_budget(client: TestClient):
    r = client.get(
        "/v1/tenants/tenant-b/budget",
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "tenant_forbidden"


def test_tenant_allowed_same_tenant_budget(client: TestClient):
    r = client.get(
        "/v1/tenants/tenant-a/budget",
        headers={"X-Tenant-Id": "tenant-a"},
    )
    assert r.status_code == 200
    assert "day" in r.json() or "month" in r.json()


def test_scheduling_preview_smoke(client: TestClient):
    body = {
        "agents": [
            {
                "agent_id": "a1",
                "skills": ["web-search"],
                "status": "online",
                "latency_ms": 100,
            },
            {
                "agent_id": "a2",
                "skills": ["web-search"],
                "status": "online",
                "latency_ms": 800,
                "load": 0.9,
            },
        ],
        "skill": "web-search",
        "requirement": {"skill": "web-search"},
        "estimated_cost": 0.1,
    }
    r = client.post("/v1/scheduling/preview", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["decision"]["selected"]["agent_id"] == "a1"


def test_scheduling_recovery_plan(client: TestClient):
    r = client.post(
        "/v1/scheduling/recovery-plan",
        json={"error_code": "TIMEOUT", "agent_id": "agent-x"},
    )
    assert r.status_code == 200
    assert r.json()["reselect"] is True
    assert "agent-x" in r.json()["exclude_agent_ids"]
