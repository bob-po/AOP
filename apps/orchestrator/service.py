"""Task service facade (compat shim).

Implementation lives in `application.task_service`. Import path
`from service import TaskService` remains stable for main.py and scripts.
"""

from __future__ import annotations

from application.task_service import TaskService

__all__ = ["TaskService"]
