"""GET /api/v1/health — liveness probe."""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "evcs-api", "phase": "1"}
