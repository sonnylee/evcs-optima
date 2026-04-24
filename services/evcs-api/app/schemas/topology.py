"""Static topology preview — what the station *looks like* given a config.

Used by ``POST /topology/preview`` (FR-01 + FR-10 + FR-11). Carries no runtime
state; see ``schemas/snapshot.py`` for the dynamic ``VisualSnapshot``.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


class ModuleGroupView(BaseModel):
    group_index: int = Field(..., ge=0, description="0-based position within the REC BD (0..3 for default 4-module layout).")
    power_kw: int
    pack_count: int = Field(..., description="power_kw // 25 (FR-11: 50→2, 75→3, 100→4).")
    pack_indices: List[int] = Field(..., description="Global 0-based pack indices within this REC BD that this group covers.")


class RecBdView(BaseModel):
    id: int
    color: str = Field(..., description="Identification color from the palette (FR-01).")
    total_capacity_kw: int
    pack_count: int
    modules: List[ModuleGroupView]
    inter_group_relay_ids: List[str] = Field(..., description="e.g. ['M1.R2','M1.R3','M1.R4'] for 4-module REC BD.")
    output_relay_ids: List[str] = Field(..., description="e.g. ['M1.O1','M1.O2'].")
    car_port_ids: List[int] = Field(..., description="Two port ids housed on this REC BD (CAR_PORTS_PER_REC_BD=2).")


class TopologyPreview(BaseModel):
    rec_bd_count: int
    car_port_count: int
    total_capacity_kw: int
    rec_bds: List[RecBdView]
    bridge_relay_ids: List[str] = Field(
        ...,
        description="Between-REC-BD bridges. 0 when N=1, 1 when N=2 (linear), N when N>=3 (ring).",
    )
