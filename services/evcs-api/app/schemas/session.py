"""Session-level schemas — holds config + car ports, plus optional step sequence (FR-09, FR-14, FR-15)."""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.control_step import ControlStepSequence


class SessionCreateRequest(BaseModel):
    system_config: SystemConfig
    car_ports: Optional[List[CarPortInput]] = None


class SessionUpdateRequest(BaseModel):
    system_config: Optional[SystemConfig] = None
    car_ports: Optional[List[CarPortInput]] = None


class SessionState(BaseModel):
    session_id: str
    system_config: SystemConfig
    car_ports: List[CarPortInput] = Field(default_factory=list)
    mode: Literal["edit", "player"] = "edit"
    step_sequence: Optional[ControlStepSequence] = None
    current_step_index: int = 0
