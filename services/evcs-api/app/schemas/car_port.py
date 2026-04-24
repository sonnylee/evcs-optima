"""Car Port input schemas — FR-06, FR-07, FR-08, FR-12, FR-13, FR-16."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.constants import MAX_REQUIRED_MAX, MAX_REQUIRED_MIN


class CarPortInput(BaseModel):
    """Canonical (already-validated) per-port state.

    Values must already be clamped to [0, 600] and aligned to 25 kW. Use
    ``validation_service.normalize_car_port`` to accept raw user input and
    produce a ``CarPortInput`` plus warnings.
    """

    port_id: int = Field(..., ge=1, description="1-based Car Port id (1..2N).")
    max_required: int = Field(..., ge=MAX_REQUIRED_MIN, le=MAX_REQUIRED_MAX)
    present: int = Field(0, ge=MAX_REQUIRED_MIN, le=MAX_REQUIRED_MAX)
    target: int = Field(0, ge=MAX_REQUIRED_MIN, le=MAX_REQUIRED_MAX)
    priority: Optional[int] = Field(None, ge=1, description="Unique priority 1..N; lower = higher priority (FR-16).")


class RawCarPortInput(BaseModel):
    """Untrusted input direct from the UI — values may be out of range or not 25 kW aligned.

    Used by the validation endpoint; the normalizer clamps & rounds, emitting warnings.
    """

    port_id: int = Field(..., ge=1)
    max_required: int
    present: int = 0
    target: int = 0
    priority: Optional[int] = None


class CarPortBatchInput(BaseModel):
    """A full set of car-port inputs keyed by port_id (exactly 2 × rec_bd_count entries)."""

    ports: List[CarPortInput]


class CarPortBatchRaw(BaseModel):
    ports: List[RawCarPortInput]
