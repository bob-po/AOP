"""WebSocket service for real-time task event streaming."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Set
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self):
        # task_id -> set of websockets
        self.task_connections: Dict[str, Set[Any]] = defaultdict(set)
        # global connections (for system-wide events)
        self.global_connections: Set[Any] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: Any, task_id: str | None = None):
        """Connect a websocket to a specific task or globally."""
        async with self._lock:
            if task_id:
                self.task_connections[task_id].add(websocket)
                logger.info(f"WebSocket connected to task {task_id}")
            else:
                self.global_connections.add(websocket)
                logger.info("Global WebSocket connected")

    async def disconnect(self, websocket: Any, task_id: str | None = None):
        """Disconnect a websocket."""
        async with self._lock:
            if task_id and task_id in self.task_connections:
                self.task_connections[task_id].discard(websocket)
                if not self.task_connections[task_id]:
                    del self.task_connections[task_id]
                logger.info(f"WebSocket disconnected from task {task_id}")
            else:
                self.global_connections.discard(websocket)
                logger.info("Global WebSocket disconnected")

    async def send_to_task(self, task_id: str, message: dict[str, Any]):
        """Send a message to all websockets connected to a specific task."""
        async with self._lock:
            websockets = self.task_connections.get(task_id, set()).copy()
        
        if websockets:
            message_str = json.dumps(message)
            disconnected = set()
            
            for websocket in websockets:
                try:
                    await websocket.send_text(message_str)
                except Exception as e:
                    logger.error(f"Failed to send to websocket: {e}")
                    disconnected.add(websocket)
            
            # Clean up disconnected websockets
            if disconnected:
                async with self._lock:
                    for ws in disconnected:
                        self.task_connections[task_id].discard(ws)

    async def send_global(self, message: dict[str, Any]):
        """Send a message to all global websockets."""
        async with self._lock:
            websockets = self.global_connections.copy()
        
        if websockets:
            message_str = json.dumps(message)
            disconnected = set()
            
            for websocket in websockets:
                try:
                    await websocket.send_text(message_str)
                except Exception as e:
                    logger.error(f"Failed to send to global websocket: {e}")
                    disconnected.add(websocket)
            
            # Clean up disconnected websockets
            if disconnected:
                async with self._lock:
                    for ws in disconnected:
                        self.global_connections.discard(ws)

    async def broadcast_task_event(self, task_id: str, event_type: str, data: dict[str, Any]):
        """Broadcast a task event to connected websockets."""
        message = {
            "type": "task_event",
            "task_id": task_id,
            "event_type": event_type,
            "data": data,
            "timestamp": asyncio.get_event_loop().time()
        }
        await self.send_to_task(task_id, message)

    async def broadcast_system_event(self, event_type: str, data: dict[str, Any]):
        """Broadcast a system-wide event."""
        message = {
            "type": "system_event",
            "event_type": event_type,
            "data": data,
            "timestamp": asyncio.get_event_loop().time()
        }
        await self.send_global(message)

    def get_connection_count(self, task_id: str | None = None) -> int:
        """Get the number of active connections."""
        if task_id:
            return len(self.task_connections.get(task_id, set()))
        return len(self.global_connections)


# Global WebSocket manager instance
manager = WebSocketManager()