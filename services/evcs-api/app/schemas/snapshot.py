"""Visual snapshot schemas (scaffolded for Phase 2 — see SPEC-WEB-API §4 FR-01..FR-06, FR-09)."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RecBdSnapshot(BaseModel):
    id: int
    color: str
    status: Literal["Occupied", "Idle"]
    power_kw: int


class PackSnapshot(BaseModel):
    """One 25 kW pack (FR-03)."""

    rec_bd_id: int
    pack_index: int = Field(..., description="0-based index within the REC BD.")
    in_use: bool
    color: str


class RelaySnapshot(BaseModel):
    id: str = Field(..., description="e.g. 'M1.R2', 'M1.O1'.")
    kind: Literal["output", "inter_group", "bridge"]
    state: Literal["Closed", "Open"]
    color: str


class CarSnapshot(BaseModel):
    port_id: int
    status: Literal["Active", "Inactive"]
    color: str
    max_required: int


class VisualSnapshot(BaseModel):
    """Full visual state of the station — FR-09 emits one of these per change."""

    rec_bds: List[RecBdSnapshot] = Field(default_factory=list)
    packs: List[PackSnapshot] = Field(default_factory=list)
    relays: List[RelaySnapshot] = Field(default_factory=list)
    cars: List[CarSnapshot] = Field(default_factory=list)
    total_power_kw: int = 0
    warnings: List[str] = Field(default_factory=list)
