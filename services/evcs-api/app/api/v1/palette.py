"""GET /api/v1/palette — default REC BD identification colors (FR-01, FR-10)."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.constants import (
    CAR_COLOR_ACTIVE,
    CAR_COLOR_INACTIVE,
    DEFAULT_PALETTE_CYCLE,
    EXTENDED_PALETTE,
    PACK_COLOR_IDLE,
    REC_BD_DEFAULT,
    RELAY_COLOR_CLOSED,
    RELAY_COLOR_OPEN,
)
from app.services.config_service import pick_palette

router = APIRouter(tags=["palette"])


@router.get("/palette")
def palette(
    count: int = Query(REC_BD_DEFAULT, ge=1, le=len(EXTENDED_PALETTE)),
    cycle: bool = Query(True, description="Use the 4-color cycle (FR-10) vs. the extended palette."),
) -> dict:
    return {
        "rec_bd_colors": pick_palette(count, cycle=cycle),
        "cycle": cycle,
        "count": count,
        "full_cycle": list(DEFAULT_PALETTE_CYCLE),
        "extended": list(EXTENDED_PALETTE),
        "semantic": {
            "relay_closed": RELAY_COLOR_CLOSED,
            "relay_open": RELAY_COLOR_OPEN,
            "car_active": CAR_COLOR_ACTIVE,
            "car_inactive": CAR_COLOR_INACTIVE,
            "pack_idle": PACK_COLOR_IDLE,
        },
    }
