"""Snapshot routes — FR-02..05 + FR-09 live recompute."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.snapshot import VisualSnapshot
from app.services.session_service import SessionStore, get_store
from app.services.state_calculation_service import compute_snapshot

router = APIRouter(tags=["snapshot"])


class SnapshotComputeRequest(BaseModel):
    system_config: SystemConfig
    car_ports: List[CarPortInput]
    cycle_palette: bool = Field(True)


@router.post("/snapshot/compute", response_model=VisualSnapshot)
def compute(req: SnapshotComputeRequest) -> VisualSnapshot:
    """Stateless recompute — used by the UI for instant FR-09 feedback."""

    return compute_snapshot(req.system_config, req.car_ports, cycle=req.cycle_palette)


@router.get("/sessions/{session_id}/snapshot", response_model=VisualSnapshot)
def session_snapshot(
    session_id: str, store: SessionStore = Depends(get_store)
) -> VisualSnapshot:
    s = store.get(session_id)
    if s is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"session {session_id} not found"
        )
    return compute_snapshot(s.system_config, s.car_ports)
