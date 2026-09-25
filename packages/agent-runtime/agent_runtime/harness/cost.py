"""Cost / usage helpers for harness adapters.

Aligns with ``scheduling.cost.CostService.aggregate`` field names:
count / estimated_cost / input_tokens / output_tokens / gpu_seconds /
wall_time_ms / currency.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from .protocol import TokenUsage

logger = logging.getLogger(__name__)

# Default USD rates — mirror apps/orchestrator/scheduling/cost.py
_DEFAULT_RATES = {
    "input_token": 0.000001,
    "output_token": 0.000002,
}


def estimate_cost(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    rates: dict[str, float] | None = None,
) -> float:
    r = {**_DEFAULT_RATES, **(rates or {})}
    return round(
        float(input_tokens) * r["input_token"] + float(output_tokens) * r["output_token"],
        8,
    )


def attach_usage(task: dict[str, Any], usage: TokenUsage) -> dict[str, Any]:
    """Write usage onto task.metadata (never raises)."""
    if usage.estimated_cost <= 0 and (usage.input_tokens or usage.output_tokens):
        usage.estimated_cost = estimate_cost(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
    meta = task.setdefault("metadata", {})
    meta["usage"] = usage.to_dict()
    return task


def report_usage_to_os(
    *,
    task_id: str,
    agent_id: str,
    usage: TokenUsage,
    root_task_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    os_url: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 5.0,
) -> bool:
    """Best-effort POST of token usage to A2A OS. Failures are swallowed."""
    base = (os_url or os.getenv("A2A_OS_URL") or os.getenv("GATEWAY_URL") or "").rstrip("/")
    if not base:
        return False
    if usage.estimated_cost <= 0 and (usage.input_tokens or usage.output_tokens):
        usage.estimated_cost = estimate_cost(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
    body = {
        "task_id": task_id,
        "root_task_id": root_task_id or task_id,
        "correlation_id": correlation_id,
        "agent_id": agent_id,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "wall_time_ms": usage.wall_time_ms,
        "estimated_cost": usage.estimated_cost,
        "currency": usage.currency,
        "execution_op": "execute",
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    key = api_key or os.getenv("A2A_OS_API_KEY") or os.getenv("GATEWAY_API_KEY") or ""
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key

    # Prefer dedicated cost path; fall back to metadata-only if 404.
    paths = [
        f"{base}/v1/scheduling/cost",
        f"{base}/v1/cost/record",
    ]
    try:
        import httpx

        with httpx.Client(timeout=timeout) as client:
            for url in paths:
                try:
                    resp = client.post(url, json=body, headers=headers)
                    if resp.status_code < 400:
                        return True
                    if resp.status_code == 404:
                        continue
                    logger.debug("cost report %s -> %s", url, resp.status_code)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("cost report failed (%s): %s", url, exc)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cost report skipped: %s", exc)
    return False


__all__ = ["estimate_cost", "attach_usage", "report_usage_to_os"]
