"""Defaults and helpers for system configuration (FR-01 palette, FR-10 REC BD count, FR-11 module powers)."""
from __future__ import annotations

from typing import List

from app.constants import (
    CAR_PORTS_PER_REC_BD,
    DEFAULT_PALETTE_CYCLE,
    EXTENDED_PALETTE,
    REC_BD_DEFAULT,
)
from app.schemas.config import RecBdConfig, SystemConfig


DEFAULT_MODULE_POWERS: List[int] = [50, 75, 75, 50]


def default_system_config(rec_bd_count: int = REC_BD_DEFAULT) -> SystemConfig:
    """Build the factory-default config: REC_BD_DEFAULT boards of 50/75/75/50 kW."""

    return SystemConfig(
        rec_bd_count=rec_bd_count,
        rec_bds=[
            RecBdConfig(id=i + 1, module_powers=list(DEFAULT_MODULE_POWERS))
            for i in range(rec_bd_count)
        ],
    )


def pick_palette(count: int, cycle: bool = True) -> List[str]:
    """Return ``count`` hex colors. FR-10 allows a fixed 4-color cycle or the extended palette."""

    if cycle:
        return [DEFAULT_PALETTE_CYCLE[i % len(DEFAULT_PALETTE_CYCLE)] for i in range(count)]
    return [EXTENDED_PALETTE[i % len(EXTENDED_PALETTE)] for i in range(count)]


def car_ports_for(rec_bd_count: int) -> int:
    return rec_bd_count * CAR_PORTS_PER_REC_BD
