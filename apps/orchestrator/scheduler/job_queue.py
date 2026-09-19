"""JobQueue: Redis Stream enqueue operations for task execution."""

from __future__ import annotations

from typing import Any

from streams import StreamClient


class JobQueue:
    """Manages job enqueue operations to Redis Streams."""

    def __init__(self, streams: StreamClient | None = None) -> None:
        self.streams = streams or StreamClient()

    def enqueue(
        self,
        *,
        task_id: str,
        node_id: str,
        node_key: str,
        skill: str,
        attempt: int = 1,
        priority: int = 100,
        exclude_agent_ids: list[str] | None = None,
        delay_seconds: float = 0,
    ) -> str:
        """Enqueue a single job to Redis Stream.
        
        Returns:
            Redis Stream message ID
        """
        return self.streams.enqueue_execution(
            task_id=task_id,
            node_id=node_id,
            node_key=node_key,
            skill=skill,
            attempt=attempt,
            priority=priority,
            exclude_agent_ids=exclude_agent_ids,
            delay_seconds=delay_seconds,
        )

    def enqueue_batch(self, jobs: list[dict[str, Any]]) -> list[str]:
        """Enqueue multiple jobs to Redis Stream.
        
        Args:
            jobs: List of job dictionaries with keys:
                  task_id, node_id, node_key, skill, attempt, 
                  exclude_agent_ids, delay_seconds
        
        Returns:
            List of Redis Stream message IDs
        """
        message_ids = []
        for job in jobs:
            message_id = self.enqueue(
                task_id=job["task_id"],
                node_id=job["node_id"],
                node_key=job["node_key"],
                skill=job["skill"],
                attempt=job.get("attempt", 1),
                exclude_agent_ids=job.get("exclude_agent_ids"),
                delay_seconds=job.get("delay_seconds", 0),
            )
            message_ids.append(message_id)
        return message_ids
