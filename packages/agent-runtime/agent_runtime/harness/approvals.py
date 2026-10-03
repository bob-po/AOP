"""Peer-agent approval inbox for harness A2A shells.

Orchestrator POSTs ``/v1/approvals`` when a hop waits on this agent.
The harness reviews (optional runner pass) then callbacks OS with
``actor=agent``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_JSON_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_approval_decision(text: str) -> dict[str, Any] | None:
    """Pull {approved, reason} from harness output. None if not parseable."""
    raw = (text or "").strip()
    if not raw:
        return None
    candidates: list[str] = [raw]
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        candidates.append(raw[start : end + 1])
    for c in candidates:
        try:
            data = json.loads(c)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if "approved" not in data and "decision" not in data:
            continue
        approved = data.get("approved")
        if approved is None:
            dec = str(data.get("decision") or "").strip().lower()
            approved = dec in {"approve", "approved", "yes", "true", "ok"}
        reason = data.get("reason") or data.get("comment") or data.get("input") or ""
        return {"approved": bool(approved), "reason": str(reason).strip()}
    low = raw.lower()
    if "reject" in low or "not approve" in low:
        return {"approved": False, "reason": raw[:400]}
    if re.search(r"\bapprove[ds]?\b", low):
        return {"approved": True, "reason": raw[:400]}
    return None


def post_decision_to_os(
    *,
    task_id: str,
    node_key: str | None,
    approved: bool,
    reason: str,
    os_url: str | None,
    api_key: str | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Callback Gateway/Orchestrator HITL with actor=agent."""
    base = (os_url or os.getenv("A2A_OS_URL") or os.getenv("GATEWAY_URL") or "").rstrip("/")
    if not base or not task_id:
        return {"ok": False, "error": "os_url_or_task_missing"}
    headers = {"Content-Type": "application/json"}
    key = api_key or os.getenv("A2A_OS_API_KEY") or os.getenv("GATEWAY_API_KEY") or ""
    if key:
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key
    path = "approve" if approved else "reject"
    url = f"{base}/v1/tasks/{task_id}/{path}"
    body: dict[str, Any] = {
        "node_key": node_key,
        "actor": "agent",
    }
    if approved:
        body["input"] = reason or None
    else:
        body["reason"] = reason or "rejected by peer agent"
    try:
        import httpx

        resp = httpx.post(url, json=body, headers=headers, timeout=timeout)
        ok = resp.status_code < 400
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "body": (resp.text or "")[:500],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("peer approval callback failed: %s", exc)
        return {"ok": False, "error": str(exc)}


class ApprovalInbox:
    def __init__(self, *, agent_id: str) -> None:
        self.agent_id = agent_id
        self._items: dict[str, dict[str, Any]] = {}

    def receive(self, body: dict[str, Any]) -> dict[str, Any]:
        aid = str(body.get("id") or uuid.uuid4())
        rec = {
            "id": aid,
            "status": "pending",
            "agent_id": self.agent_id,
            "task_id": body.get("task_id"),
            "node_key": body.get("node_key"),
            "approval_mode": body.get("approval_mode") or "agent",
            "approver_agent": body.get("approver_agent") or self.agent_id,
            "reason": body.get("reason"),
            "hitl": body.get("hitl") if isinstance(body.get("hitl"), dict) else {},
            "created_at": utc_now(),
            "decided_at": None,
            "approved": None,
            "decision_reason": None,
            "callback": None,
        }
        self._items[aid] = rec
        return rec

    def get(self, approval_id: str) -> dict[str, Any] | None:
        return self._items.get(approval_id)

    def list_pending(self) -> list[dict[str, Any]]:
        return [v for v in self._items.values() if v.get("status") == "pending"]

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._items.values())

    def decide(
        self,
        approval_id: str,
        *,
        approved: bool,
        reason: str = "",
        os_url: str | None = None,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        rec = self._items.get(approval_id)
        if not rec:
            raise KeyError(approval_id)
        if rec.get("status") != "pending":
            return rec
        rec["status"] = "approved" if approved else "rejected"
        rec["approved"] = bool(approved)
        rec["decision_reason"] = reason
        rec["decided_at"] = utc_now()
        rec["callback"] = post_decision_to_os(
            task_id=str(rec.get("task_id") or ""),
            node_key=rec.get("node_key"),
            approved=approved,
            reason=reason,
            os_url=os_url,
            api_key=api_key,
        )
        return rec


def approval_prompt(rec: dict[str, Any]) -> str:
    return (
        "You are the designated peer approver for another agent's work on A2A OS.\n"
        f"Task ID: {rec.get('task_id')}\n"
        f"Node: {rec.get('node_key')}\n"
        f"Mode: {rec.get('approval_mode')}\n"
        f"Request reason: {rec.get('reason') or '(none)'}\n\n"
        "Decide whether this hop should continue.\n"
        'Reply with JSON only: {"approved": true|false, "reason": "short justification"}'
    )
