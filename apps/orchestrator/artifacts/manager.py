"""ArtifactManager: MinIO store + node-output metadata merge."""

from __future__ import annotations

import json
from typing import Any

from scheduler import Scheduler

from . import ArtifactStore


class ArtifactManager:
    """Unified artifact listing for API consumers."""

    def __init__(
        self,
        *,
        store: ArtifactStore | None = None,
        scheduler: Scheduler | None = None,
    ) -> None:
        self.store = store or ArtifactStore()
        self.scheduler = scheduler or Scheduler()

    def list_all(
        self,
        *,
        task_id: str | None = None,
        type_filter: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self.store.list_all_artifacts(
            task_id=task_id,
            type_filter=type_filter,
            limit=limit,
        )

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        stored = self.store.list_task_artifacts(task_id)
        task = self.scheduler.get_task(task_id)
        if not task:
            return stored
        meta_from_nodes: list[dict[str, Any]] = []
        for n in task.get("nodes") or []:
            detail = self.scheduler.get_node(task_id, n["id"])
            if not detail:
                continue
            out = detail.get("output_json") or {}
            if isinstance(out, str):
                out = json.loads(out)
            if not isinstance(out, dict):
                continue
            for art in out.get("artifacts") or []:
                meta_from_nodes.append(
                    {
                        "node_id": n["id"],
                        "name": art.get("name"),
                        "type": art.get("type"),
                        "uri": art.get("uri"),
                        "mime_type": art.get("mime_type"),
                        "size": art.get("size"),
                        "source": "node_output",
                    }
                )
        by_uri: dict[str, dict[str, Any]] = {}
        for item in meta_from_nodes + stored:
            uri = item.get("uri")
            if not uri:
                continue
            by_uri[uri] = {**by_uri.get(uri, {}), **item}
        return list(by_uri.values())
