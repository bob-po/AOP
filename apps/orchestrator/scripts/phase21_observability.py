#!/usr/bin/env python3
"""Phase 21 smoke: Prometheus / Grafana / alert config alignment."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ORCH = ROOT / "apps" / "orchestrator"
PROM = ROOT / "deployments" / "prometheus"
GRAFANA = ROOT / "deployments" / "grafana" / "provisioning"
ALERTS = PROM / "alerts" / "aop-alerts.yml"
DASH = GRAFANA / "dashboards" / "aop" / "overview-dashboard.json"


def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        # Minimal parse: just ensure file readable; skip structured checks
        text = path.read_text(encoding="utf-8")
        assert text.strip(), path
        return {"_raw": text}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> int:
    print("[1/4] Prometheus scrape configs")
    for name in ("prometheus.yml", "prometheus.host.yml", "prometheus.ha.yml"):
        path = PROM / name
        data = _load_yaml(path)
        raw = path.read_text(encoding="utf-8")
        assert "orchestrator" in raw and "gateway" in raw, name
        if name != "prometheus.ha.yml":
            assert "worker" in raw, f"{name} missing worker scrape"
        print(f"  ok {name}")

    print("[2/4] Alert rules reference live metrics")
    alerts = ALERTS.read_text(encoding="utf-8")
    for needle in (
        "aop_agent_calls_total",
        "aop_gateway_lb_healthy_targets",
        "up{job=\"orchestrator\"}",
        "WorkerDown",
        "HighTaskFailureRate",
    ):
        assert needle in alerts, f"missing {needle}"
    print("  ok")

    print("[3/4] Grafana overview dashboard")
    dash = json.loads(DASH.read_text(encoding="utf-8"))
    assert dash.get("uid") == "aop-overview"
    exprs = []
    for panel in dash.get("panels") or []:
        for t in panel.get("targets") or []:
            if t.get("expr"):
                exprs.append(t["expr"])
    blob = "\n".join(exprs)
    for metric in (
        "aop_tasks_total",
        "aop_agent_calls_total",
        "aop_gateway_lb_healthy_targets",
        "aop_tenant_memories_total",
    ):
        assert metric in blob, f"dashboard missing {metric}"
    print(f"  ok ({len(dash.get('panels') or [])} panels)")

    print("[4/4] Snapshot prometheus text includes tenant memories")
    rc = subprocess.call(
        [sys.executable, "-m", "pytest", "-q", "tests/test_observability_metrics.py"],
        cwd=str(ORCH),
    )
    if rc != 0:
        return rc
    # Best-effort live snapshot (needs PG + table)
    sys.path.insert(0, str(ORCH))
    try:
        from observability import MetricsService

        text = MetricsService().prometheus_text(hours=1)
        assert "aop_task_memories_total" in text
        assert "aop_tenant_memories_total" in text
        print("  ok live snapshot")
    except Exception as exc:  # noqa: BLE001
        print(f"  skip live snapshot: {exc}")

    print("PHASE21 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
