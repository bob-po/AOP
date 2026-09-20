"""Periodic agent health probe — updates PG status + Redis skill index."""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import psycopg
import redis
from psycopg.rows import dict_row
from db import connect

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class HealthMonitor:
    def __init__(
        self,
        *,
        interval: float = 30.0,
        timeout: float = 5.0,
        database_url: str | None = None,
        redis_url: str | None = None,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        self.interval = interval
        self.timeout = timeout
        self.database_url = database_url or os.getenv(
            "DATABASE_URL",
            "postgresql://aop:aop@127.0.0.1:5432/aop",
        )
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
        self.tenant_id = tenant_id
        self.redis = redis.Redis.from_url(self.redis_url, decode_responses=True)

    def run_forever(self) -> None:
        print(f"[health] started interval={self.interval}s")
        while True:
            try:
                results = self.probe_all()
                online = sum(1 for r in results if r["healthy"])
                print(f"[health] probed={len(results)} online={online}")
                for r in results:
                    mark = "ok" if r["healthy"] else "FAIL"
                    print(f"  {mark} {r['agent_key']} -> {r['status']} ({r.get('error') or 'ok'})")
            except KeyboardInterrupt:
                print("[health] stopping")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[health] loop error: {exc}")
            time.sleep(self.interval)

    def probe_all(self) -> list[dict[str, Any]]:
        agents = self._list_agents()
        out: list[dict[str, Any]] = []
        for agent in agents:
            if agent["status"] == "disabled":
                out.append(
                    {
                        **agent,
                        "healthy": False,
                        "error": "disabled",
                        "status": "disabled",
                    }
                )
                continue
            healthy, err = self._probe(agent.get("endpoint") or "")
            new_status = "online" if healthy else "offline"
            if new_status != agent["status"]:
                self._set_status(agent["agent_id"], agent.get("skills") or [], new_status)
            out.append(
                {
                    **agent,
                    "healthy": healthy,
                    "error": err,
                    "status": new_status,
                }
            )
        return out

    def _list_agents(self) -> list[dict[str, Any]]:
        sql = """
            SELECT a.id::text AS agent_id, a.agent_key, a.name, a.status,
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
            ORDER BY a.agent_key
        """
        with connect(self.database_url) as conn:
            rows = conn.execute(sql, (self.tenant_id,)).fetchall()
        return [dict(r) for r in rows]

    def _probe(self, endpoint: str) -> tuple[bool, str | None]:
        if not endpoint:
            return False, "missing endpoint"
        base = endpoint.rstrip("/")
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                resp = client.get(f"{base}/health")
                if resp.status_code < 300:
                    return True, None
                # fallback: agent card
                card = client.get(f"{base}/.well-known/agent-card.json")
                if card.status_code < 300:
                    return True, None
                return False, f"health={resp.status_code} card={card.status_code}"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _set_status(self, agent_id: str, skills: list[str], status: str) -> None:
        with connect(self.database_url, row_factory=None) as conn:
            conn.execute(
                "UPDATE agents SET status = %s, updated_at = %s WHERE id = %s::uuid",
                (status, _utc_now(), agent_id),
            )
            conn.commit()

        pipe = self.redis.pipeline()
        old = list(self.redis.smembers(f"agent:{agent_id}:skills") or [])
        for sk in old:
            pipe.srem(f"agent:skill:{sk}", agent_id)
        pipe.delete(f"agent:{agent_id}:skills")
        pipe.hset(
            f"agent:{agent_id}:state",
            mapping={
                "status": status,
                "updated_at": _utc_now().isoformat(),
            },
        )
        if status in {"online", "running"}:
            for sk in skills:
                pipe.sadd(f"agent:skill:{sk}", agent_id)
                pipe.sadd(f"agent:{agent_id}:skills", sk)
        pipe.execute()


def main() -> None:
    parser = argparse.ArgumentParser(description="AOP agent health monitor")
    parser.add_argument("--interval", type=float, default=float(os.getenv("HEALTH_INTERVAL", "30")))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    mon = HealthMonitor(interval=args.interval)
    if args.once:
        for r in mon.probe_all():
            print(r)
        return
    mon.run_forever()


if __name__ == "__main__":
    main()
