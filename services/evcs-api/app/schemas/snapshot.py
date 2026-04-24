"""Visual snapshot schemas — FR-02, FR-03, FR-04, FR-05, FR-09.

The snapshot is a pure function of ``(SystemConfig, List[CarPortInput])`` and
is recomputed on every Max Required change (FR-09).
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class RecBdSnapshot(BaseModel):
    """FR-02: per-REC-BD live power + status."""

    id: int
    color: str
    status: Literal["Occupied", "Idle"]
    power_kw: int
    used_packs: int
    total_packs: int


class PackSnapshot(BaseModel):
    """FR-03: one 25 kW pack. Color = consuming port's *home* REC BD color (or idle grey)."""

    rec_bd_id: int = Field(..., description="REC BD the pack physically lives in.")
    pack_index: int = Field(..., ge=0, description="0-based index within the REC BD.")
    in_use: bool
    owner_port_id: Optional[int] = Field(None, description="Port consuming this pack, if any.")
    color: str


class RelaySnapshot(BaseModel):
    """FR-04: output / inter-group / bridge relay state."""

    id: str = Field(..., description="'M1.O1', 'M1.R2', or 'B_1_2'.")
    kind: Literal["output", "inter_group", "bridge"]
    state: Literal["Closed", "Open"]
    color: str
    owner_port_id: Optional[int] = Field(None, description="Output relays only: the port they feed.")
    rec_bd_id: Optional[int] = Field(None, description="Output / inter_group relays: their home REC BD.")


class CarSnapshot(BaseModel):
    """FR-05: car icon color based on Output Relay state & Max Required."""

    port_id: int
    rec_bd_id: int = Field(..., description="Home REC BD id = ceil(port_id/2).")
    status: Literal["Active", "Inactive"]
    color: str
    max_required: int
    allocated_kw: int = Field(..., description="Actual kW allocated by this snapshot (may be < max_required on capacity shortage).")
    priority: Optional[int] = None


class VisualSnapshot(BaseModel):
    """FR-09 emits one of these per change."""

    rec_bds: List[RecBdSnapshot] = Field(default_factory=list)
    packs: List[PackSnapshot] = Field(default_factory=list)
    relays: List[RelaySnapshot] = Field(default_factory=list)
    cars: List[CarSnapshot] = Field(default_factory=list)
    total_power_kw: int = 0
    total_requested_kw: int = 0
    warnings: List[str] = Field(default_factory=list)
