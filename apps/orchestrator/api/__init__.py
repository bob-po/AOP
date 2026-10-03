"""HTTP API route packages split out of ``main.py``."""

from __future__ import annotations

from fastapi import FastAPI

from api.agents import router as agents_router
from api.billing import router as billing_router
from api.discovery import router as discovery_router
from api.governance import router as governance_router
from api.marketplace import router as marketplace_router
from api.memory import router as memory_router
from api.preflight import router as preflight_router
from api.runtime import router as runtime_router
from api.scheduling import router as scheduling_router
from api.task_ops import router as task_ops_router
from api.tasks import router as tasks_router
from api.visual_runtime import router as visual_runtime_router
from api.workflows import router as workflows_router


def register_api_routes(app: FastAPI) -> None:
    app.include_router(tasks_router)
    app.include_router(task_ops_router)
    app.include_router(visual_runtime_router)
    app.include_router(marketplace_router)
    app.include_router(billing_router)
    app.include_router(governance_router)
    app.include_router(scheduling_router)
    app.include_router(discovery_router)
    app.include_router(preflight_router)
    app.include_router(runtime_router)
    app.include_router(agents_router)
    app.include_router(memory_router)
    app.include_router(workflows_router)
