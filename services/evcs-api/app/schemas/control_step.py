"""Control step schemas (scaffolded for Phase 3 — see SPEC-WEB-API §4 FR-14, FR-15)."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from app.schemas.snapshot import VisualSnapshot


class ControlStep(BaseModel):
    step_index: int = Field(..., ge=0)
    description: str
    snapshot: VisualSnapshot


class ControlStepSequence(BaseModel):
    total_steps: int
    steps: List[ControlStep] = Field(default_factory=list)
    initial_state: VisualSnapshot
    warnings: List[str] = Field(default_factory=list)
