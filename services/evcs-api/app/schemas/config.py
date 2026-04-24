"""System configuration schemas — FR-10 (REC BD count), FR-11 (module powers)."""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator, model_validator

from app.constants import (
    POWER_MAX_PER_MODULE,
    POWER_MIN_PER_MODULE,
    REC_BD_MAX,
    REC_BD_MIN,
    STEP_KW,
)


class RecBdConfig(BaseModel):
    """One REC BD's module-power list (FR-11). Each module is 50~100 kW, multiple of 25."""

    id: int = Field(..., ge=1, description="1-based REC BD id.")
    module_powers: List[int] = Field(..., min_length=1, description="Per-module power in kW, e.g. [50, 75, 75, 50].")

    @field_validator("module_powers")
    @classmethod
    def _check_modules(cls, v: List[int]) -> List[int]:
        for p in v:
            if p < POWER_MIN_PER_MODULE or p > POWER_MAX_PER_MODULE:
                raise ValueError(
                    f"module power {p} kW out of range [{POWER_MIN_PER_MODULE}, {POWER_MAX_PER_MODULE}]"
                )
            if p % STEP_KW != 0:
                raise ValueError(f"module power {p} kW must be a multiple of {STEP_KW}")
        return v

    @property
    def total_capacity_kw(self) -> int:
        return sum(self.module_powers)

    @property
    def pack_count(self) -> int:
        """Total number of 25 kW packs in this REC BD (FR-03)."""
        return sum(p // STEP_KW for p in self.module_powers)


class SystemConfig(BaseModel):
    """Top-level charging-station configuration (FR-10)."""

    rec_bd_count: int = Field(..., ge=REC_BD_MIN, le=REC_BD_MAX)
    rec_bds: List[RecBdConfig] = Field(..., min_length=REC_BD_MIN, max_length=REC_BD_MAX)

    @model_validator(mode="after")
    def _check_len_matches_count(self) -> "SystemConfig":
        if len(self.rec_bds) != self.rec_bd_count:
            raise ValueError(
                f"rec_bds length ({len(self.rec_bds)}) must equal rec_bd_count ({self.rec_bd_count})"
            )
        ids = [b.id for b in self.rec_bds]
        if ids != list(range(1, self.rec_bd_count + 1)):
            raise ValueError(f"rec_bds ids must be 1..{self.rec_bd_count} in order, got {ids}")
        return self

    @property
    def total_capacity_kw(self) -> int:
        return sum(b.total_capacity_kw for b in self.rec_bds)

    @property
    def car_port_count(self) -> int:
        return self.rec_bd_count * 2
