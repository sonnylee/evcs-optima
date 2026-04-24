"""GET /api/v1/constants — publishes FR-08, FR-10, FR-11 bounds so the UI can't drift."""
from __future__ import annotations

from fastapi import APIRouter

from app.constants import (
    CAR_PORTS_PER_REC_BD,
    MAX_REQUIRED_MAX,
    MAX_REQUIRED_MIN,
    POWER_MAX_PER_MODULE,
    POWER_MIN_PER_MODULE,
    REC_BD_DEFAULT,
    REC_BD_MAX,
    REC_BD_MIN,
    STEP_KW,
)

router = APIRouter(tags=["constants"])


@router.get("/constants")
def constants() -> dict:
    return {
        "max_required": {
            "min": MAX_REQUIRED_MIN,
            "max": MAX_REQUIRED_MAX,
            "step": STEP_KW,
        },
        "rec_bd": {
            "min": REC_BD_MIN,
            "max": REC_BD_MAX,
            "default": REC_BD_DEFAULT,
            "car_ports_per_rec_bd": CAR_PORTS_PER_REC_BD,
        },
        "module_power": {
            "min": POWER_MIN_PER_MODULE,
            "max": POWER_MAX_PER_MODULE,
            "step": STEP_KW,
        },
    }
