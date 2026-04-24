"""POST /api/v1/topology/preview — FR-01 + FR-10 + FR-11 static layout."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas.config import SystemConfig
from app.schemas.topology import TopologyPreview
from app.services.config_service import build_topology

router = APIRouter(prefix="/topology", tags=["topology"])


class TopologyPreviewRequest(BaseModel):
    system_config: SystemConfig
    cycle_palette: bool = Field(True, description="Use 4-color cycle (FR-10) vs extended palette.")


@router.post("/preview", response_model=TopologyPreview)
def preview(req: TopologyPreviewRequest) -> TopologyPreview:
    return build_topology(req.system_config, cycle=req.cycle_palette)
