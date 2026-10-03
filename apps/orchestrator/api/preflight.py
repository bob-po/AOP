"""GET /v1/preflight — Console operator banner."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from preflight import collect_preflight

router = APIRouter(tags=["preflight"])


@router.get("/v1/preflight")
def preflight() -> dict[str, Any]:
    return collect_preflight()
