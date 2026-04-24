"""Input validation & normalization — FR-08, FR-10, FR-11, FR-12, FR-13, FR-16.

The normalizers *clamp and round* raw user input and emit warnings
(FR-12 style: 'input 130 → 125 kW', 'input 630 → 600 kW', 'input -10 → 0 kW').
The validators *reject* anything still invalid after normalization and
return a list of ``ErrorDetail``.
"""
from __future__ import annotations

from typing import List, Tuple

from app.constants import (
    MAX_REQUIRED_MAX,
    MAX_REQUIRED_MIN,
    POWER_MAX_PER_MODULE,
    POWER_MIN_PER_MODULE,
    REC_BD_MAX,
    REC_BD_MIN,
    STEP_KW,
)
from app.schemas.car_port import CarPortInput, RawCarPortInput
from app.schemas.config import RecBdConfig, SystemConfig
from app.schemas.error import ErrorDetail, WarningDetail


# ---------------------------------------------------------------------------
# FR-11 module-power list parsing
# ---------------------------------------------------------------------------

def parse_module_powers(raw: str) -> Tuple[List[int], List[ErrorDetail]]:
    """Parse a comma-separated string like '50, 75, 75, 50' into a list of ints.

    Returns (powers, errors). Empty list + errors on any parse failure.
    """

    errors: List[ErrorDetail] = []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        errors.append(ErrorDetail(code="MODULE_POWERS_EMPTY", message="module power list is empty"))
        return [], errors

    powers: List[int] = []
    for i, p in enumerate(parts):
        try:
            v = int(p)
        except ValueError:
            errors.append(
                ErrorDetail(
                    code="MODULE_POWER_NOT_INT",
                    field=f"module_powers[{i}]",
                    message=f"'{p}' is not an integer",
                )
            )
            continue
        powers.append(v)

    if errors:
        return [], errors
    return powers, errors


def validate_module_powers(powers: List[int], field_prefix: str = "module_powers") -> List[ErrorDetail]:
    errors: List[ErrorDetail] = []
    for i, p in enumerate(powers):
        f = f"{field_prefix}[{i}]"
        if p % STEP_KW != 0:
            errors.append(
                ErrorDetail(
                    code="MODULE_POWER_NOT_MULTIPLE_OF_25",
                    field=f,
                    message=f"{p} kW must be a multiple of {STEP_KW}",
                )
            )
        if p < POWER_MIN_PER_MODULE or p > POWER_MAX_PER_MODULE:
            errors.append(
                ErrorDetail(
                    code="MODULE_POWER_OUT_OF_RANGE",
                    field=f,
                    message=f"{p} kW out of [{POWER_MIN_PER_MODULE}, {POWER_MAX_PER_MODULE}]",
                )
            )
    return errors


# ---------------------------------------------------------------------------
# FR-12 Max Required normalization (clamp + round-to-25)
# ---------------------------------------------------------------------------

def _round_to_step(v: int) -> int:
    return int(round(v / STEP_KW)) * STEP_KW


def normalize_power(
    value: int,
    field: str,
    lo: int = MAX_REQUIRED_MIN,
    hi: int = MAX_REQUIRED_MAX,
) -> Tuple[int, List[WarningDetail]]:
    """Clamp to [lo, hi] and round to nearest 25 kW. Emits a warning per adjustment."""

    warnings: List[WarningDetail] = []
    original = value
    v = value

    if v < lo:
        warnings.append(
            WarningDetail(
                code="BELOW_MIN",
                field=field,
                message=f"value {original} below minimum {lo} kW, clamped to {lo}",
                original_value=original,
                adjusted_value=lo,
            )
        )
        v = lo
    elif v > hi:
        warnings.append(
            WarningDetail(
                code="ABOVE_MAX",
                field=field,
                message=f"value {original} above maximum {hi} kW, clamped to {hi}",
                original_value=original,
                adjusted_value=hi,
            )
        )
        v = hi

    if v % STEP_KW != 0:
        rounded = _round_to_step(v)
        rounded = max(lo, min(hi, rounded))
        warnings.append(
            WarningDetail(
                code="NOT_MULTIPLE_OF_25",
                field=field,
                message=f"value {v} rounded to {rounded} kW (must be multiple of {STEP_KW})",
                original_value=v,
                adjusted_value=rounded,
            )
        )
        v = rounded

    return v, warnings


def normalize_car_port(raw: RawCarPortInput) -> Tuple[CarPortInput, List[WarningDetail]]:
    """Clamp + round all three power fields; return canonical ``CarPortInput`` + warnings."""

    warnings: List[WarningDetail] = []
    prefix = f"car_ports[{raw.port_id}]"

    max_req, w = normalize_power(raw.max_required, f"{prefix}.max_required")
    warnings.extend(w)

    present, w = normalize_power(raw.present, f"{prefix}.present")
    warnings.extend(w)

    target, w = normalize_power(raw.target, f"{prefix}.target")
    warnings.extend(w)

    return (
        CarPortInput(
            port_id=raw.port_id,
            max_required=max_req,
            present=present,
            target=target,
            priority=raw.priority,
        ),
        warnings,
    )


# ---------------------------------------------------------------------------
# FR-10 REC BD count
# ---------------------------------------------------------------------------

def validate_rec_bd_count(n: int) -> List[ErrorDetail]:
    if n < REC_BD_MIN or n > REC_BD_MAX:
        return [
            ErrorDetail(
                code="REC_BD_COUNT_OUT_OF_RANGE",
                field="rec_bd_count",
                message=f"REC BD count {n} out of [{REC_BD_MIN}, {REC_BD_MAX}]",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# FR-16 per-port priority uniqueness & range
# ---------------------------------------------------------------------------

def validate_priorities(car_ports: List[CarPortInput], rec_bd_count: int) -> List[ErrorDetail]:
    """Priorities (if any set) must be unique integers in [1, N] where N = 2 × rec_bd_count.

    Per FR-16: at least two ports must have priority set for ``Apply and Generate``
    to proceed; that specific check is enforced at control-step generation time,
    not here — here we only validate the shape of whatever priorities are present.
    """

    n = rec_bd_count * 2
    errors: List[ErrorDetail] = []
    seen: dict[int, int] = {}  # priority -> port_id

    for cp in car_ports:
        if cp.priority is None:
            continue
        f = f"car_ports[{cp.port_id}].priority"
        if cp.priority < 1 or cp.priority > n:
            errors.append(
                ErrorDetail(
                    code="PRIORITY_OUT_OF_RANGE",
                    field=f,
                    message=f"priority {cp.priority} out of [1, {n}]",
                )
            )
            continue
        if cp.priority in seen:
            errors.append(
                ErrorDetail(
                    code="PRIORITY_DUPLICATE",
                    field=f,
                    message=(
                        f"priority {cp.priority} already assigned to port {seen[cp.priority]}"
                    ),
                )
            )
        else:
            seen[cp.priority] = cp.port_id

    return errors


def priorities_ready_for_apply(car_ports: List[CarPortInput]) -> bool:
    """FR-16: at least 2 ports must have a priority set before Apply and Generate runs."""

    return sum(1 for cp in car_ports if cp.priority is not None) >= 2


# ---------------------------------------------------------------------------
# FR-13 Target-over-capacity check
# ---------------------------------------------------------------------------

def validate_target_within_capacity(
    car_ports: List[CarPortInput], system: SystemConfig
) -> List[ErrorDetail]:
    """Sum of Target across all ports must not exceed total station capacity."""

    total_target = sum(cp.target for cp in car_ports)
    total_capacity = system.total_capacity_kw
    if total_target > total_capacity:
        return [
            ErrorDetail(
                code="TARGET_EXCEEDS_CAPACITY",
                field="car_ports.target",
                message=(
                    f"sum of Target ({total_target} kW) exceeds total station "
                    f"capacity ({total_capacity} kW)"
                ),
            )
        ]
    return []


# ---------------------------------------------------------------------------
# Whole-session validation
# ---------------------------------------------------------------------------

def validate_car_port_count(car_ports: List[CarPortInput], system: SystemConfig) -> List[ErrorDetail]:
    expected = system.car_port_count
    if len(car_ports) != expected:
        return [
            ErrorDetail(
                code="CAR_PORT_COUNT_MISMATCH",
                field="car_ports",
                message=(
                    f"expected {expected} car ports (2 × {system.rec_bd_count} REC BDs), "
                    f"got {len(car_ports)}"
                ),
            )
        ]
    ids = sorted(cp.port_id for cp in car_ports)
    if ids != list(range(1, expected + 1)):
        return [
            ErrorDetail(
                code="CAR_PORT_IDS_INVALID",
                field="car_ports.port_id",
                message=f"car port ids must be 1..{expected}, got {ids}",
            )
        ]
    return []
