"""POST /api/v1/validate/* — FR-08, 10, 11, 12, 13, 16 validation endpoints."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas.car_port import CarPortBatchRaw, CarPortInput
from app.schemas.config import RecBdConfig, SystemConfig
from app.schemas.error import ErrorDetail, WarningDetail
from app.services.validation_service import (
    normalize_car_port,
    parse_module_powers,
    priorities_ready_for_apply,
    validate_car_port_count,
    validate_module_powers,
    validate_priorities,
    validate_rec_bd_count,
    validate_target_within_capacity,
)

router = APIRouter(prefix="/validate", tags=["validation"])


# -- module-power string --------------------------------------------------

class ModulePowerStringRequest(BaseModel):
    raw: str = Field(..., description="Comma-separated module powers, e.g. '50, 75, 75, 50'.")


class ModulePowerStringResponse(BaseModel):
    powers: List[int]
    total_capacity_kw: int
    pack_count: int
    errors: List[ErrorDetail]


@router.post("/module-powers", response_model=ModulePowerStringResponse)
def validate_module_powers_string(req: ModulePowerStringRequest) -> ModulePowerStringResponse:
    powers, parse_errors = parse_module_powers(req.raw)
    errors = list(parse_errors)
    if not errors:
        errors.extend(validate_module_powers(powers))

    total = sum(powers) if not errors else 0
    pack_count = sum(p // 25 for p in powers) if not errors else 0
    return ModulePowerStringResponse(
        powers=powers if not errors else [],
        total_capacity_kw=total,
        pack_count=pack_count,
        errors=errors,
    )


# -- car-port batch normalize + validate ----------------------------------

class CarPortBatchValidateRequest(BaseModel):
    batch: CarPortBatchRaw
    system_config: Optional[SystemConfig] = None


class CarPortBatchValidateResponse(BaseModel):
    ports: List[CarPortInput]
    warnings: List[WarningDetail]
    errors: List[ErrorDetail]
    apply_ready: bool = Field(
        ..., description="True iff at least 2 ports have priority set (FR-16 precondition)."
    )


@router.post("/car-ports", response_model=CarPortBatchValidateResponse)
def validate_car_ports(req: CarPortBatchValidateRequest) -> CarPortBatchValidateResponse:
    normalized: List[CarPortInput] = []
    warnings: List[WarningDetail] = []
    for raw in req.batch.ports:
        cp, w = normalize_car_port(raw)
        normalized.append(cp)
        warnings.extend(w)

    errors: List[ErrorDetail] = []
    if req.system_config is not None:
        errors.extend(validate_car_port_count(normalized, req.system_config))
        errors.extend(validate_priorities(normalized, req.system_config.rec_bd_count))
        errors.extend(validate_target_within_capacity(normalized, req.system_config))
    else:
        # best-effort: still check priority duplicates against whatever count caller implies
        # (use max priority + max port_id // 2 as a heuristic N)
        implied_n = max((cp.port_id for cp in normalized), default=2)
        implied_rec_bd = (implied_n + 1) // 2
        errors.extend(validate_priorities(normalized, implied_rec_bd))

    return CarPortBatchValidateResponse(
        ports=normalized,
        warnings=warnings,
        errors=errors,
        apply_ready=priorities_ready_for_apply(normalized) and not errors,
    )


# -- system config validation ---------------------------------------------

class SystemConfigValidateResponse(BaseModel):
    errors: List[ErrorDetail]
    total_capacity_kw: int
    car_port_count: int


@router.post("/system-config", response_model=SystemConfigValidateResponse)
def validate_system_config_endpoint(cfg: SystemConfig) -> SystemConfigValidateResponse:
    errors: List[ErrorDetail] = []
    errors.extend(validate_rec_bd_count(cfg.rec_bd_count))
    for b in cfg.rec_bds:
        errors.extend(
            validate_module_powers(
                b.module_powers, field_prefix=f"rec_bds[{b.id}].module_powers"
            )
        )
    return SystemConfigValidateResponse(
        errors=errors,
        total_capacity_kw=cfg.total_capacity_kw if not errors else 0,
        car_port_count=cfg.car_port_count,
    )
