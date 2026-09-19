"""Application layer: TaskManager + TaskService facade."""

from .task_manager import TaskManager
from .task_service import TaskService

__all__ = ["TaskManager", "TaskService"]
