"""EvcsCoreAdapter — orchestration entry point for FR-14 Apply and Generate.

Phase 3 / Step F14.2 makes this layer fully async: both ``_present_warnings``
and ``generate_control_steps`` are ``async def`` and call
``WebSessionEngine.create()`` directly (no ``compute_snapshot`` indirection).
The two endpoint engines (initial / final) are independent — separate
``SimulationEngine`` instances built from OFF, settled to the demand-specific
steady state, and discarded after the snapshot is read (SPEC-WEB-API §3.3).

Routes use this module as their single entry point.
"""
from __future__ import annotations

from typing import List

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.control_step import ControlStepSequence
from app.schemas.error import ErrorDetail
from app.services.validation_service import (
    priorities_ready_for_apply,
    validate_target_within_capacity,
)
from app.services.web_session_engine import WebSessionEngine

from app.adapters import step_planner


class AdapterError(Exception):
    """Base for adapter pre-validation failures (route maps to HTTP 422)."""

    def __init__(self, errors: List[ErrorDetail]):
        self.errors = errors
        super().__init__("; ".join(e.message for e in errors))


class TargetExceedsCapacityError(AdapterError):
    pass


class PrioritiesIncompleteError(AdapterError):
    pass


# ---------------------------------------------------------------------------
# Pre-warning detection (FR-14 "unreasonable Present")
# ---------------------------------------------------------------------------

async def _present_warnings(
    system: SystemConfig, car_ports: List[CarPortInput]
) -> List[str]:
    """FR-14: warn if user-entered Present is unreasonable.

    Detected cases:
    * ``present > max_required`` — present exceeds the per-port ceiling.
    * ``present`` not aligned to 25 kW.
    * Sum of ``present`` exceeds station capacity (resources unavailable).
    * The recomputed allocation under ``present`` does not match the
      user-entered ``present`` (i.e. station can't actually deliver this).
    """

    warnings: List[str] = []

    for cp in car_ports:
        if cp.present > cp.max_required:
            warnings.append(
                f"Port {cp.port_id}: Present ({cp.present} kW) exceeds Max Required "
                f"({cp.max_required} kW); suggested {cp.max_required} kW."
            )
        if cp.present % 25 != 0:
            warnings.append(
                f"Port {cp.port_id}: Present ({cp.present} kW) is not a multiple of 25 kW."
            )

    total_present = sum(cp.present for cp in car_ports)
    if total_present > system.total_capacity_kw:
        warnings.append(
            f"Sum of Present ({total_present} kW) exceeds station capacity "
            f"({system.total_capacity_kw} kW); Present is unreasonable."
        )

    # Allocation feasibility — can the station actually deliver `present` per port?
    if total_present > 0:
        present_ports = [
            cp.model_copy(update={"max_required": cp.present}) for cp in car_ports
        ]
        engine = await WebSessionEngine.create(system, present_ports)
        snap = engine.to_visual_snapshot()
        for c in snap.cars:
            cp = next(p for p in car_ports if p.port_id == c.port_id)
            if cp.present > 0 and c.allocated_kw < cp.present:
                warnings.append(
                    f"Port {cp.port_id}: Present ({cp.present} kW) is not deliverable "
                    f"under current allocation; suggested {c.allocated_kw} kW."
                )

    return warnings


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def generate_control_steps(
    system_config: SystemConfig, car_ports: List[CarPortInput]
) -> ControlStepSequence:
    """Validate inputs, build endpoint snapshots, and plan the transition."""

    # 1. Hard pre-validation (FR-14)
    cap_errors = validate_target_within_capacity(car_ports, system_config)
    if cap_errors:
        raise TargetExceedsCapacityError(cap_errors)

    if not priorities_ready_for_apply(car_ports):
        raise PrioritiesIncompleteError(
            [
                ErrorDetail(
                    code="PRIORITIES_INSUFFICIENT",
                    field="car_ports.priority",
                    message=(
                        "FR-16: at least 2 car ports must have a priority set before "
                        "Apply and Generate can run."
                    ),
                )
            ]
        )

    # 2. Soft warnings (do not abort)
    warnings = await _present_warnings(system_config, car_ports)

    # 3. Endpoint snapshots — two independent WebSessionEngine instances,
    #    each built from OFF and settled to its own demand-specific steady
    #    state (SPEC-WEB-API §3.3 步驟一 / 步驟二).
    initial_ports = [
        cp.model_copy(update={"max_required": cp.present}) for cp in car_ports
    ]
    initial_engine = await WebSessionEngine.create(system_config, initial_ports)
    initial_state = initial_engine.to_visual_snapshot()

    target_ports = [
        cp.model_copy(update={"max_required": cp.target}) for cp in car_ports
    ]
    final_engine = await WebSessionEngine.create(system_config, target_ports)
    final_state = final_engine.to_visual_snapshot()

    # 4. Identity short-circuit
    if initial_state == final_state:
        return ControlStepSequence(
            total_steps=0,
            steps=[],
            initial_state=initial_state,
            warnings=warnings + ["No change required"],
        )

    # 5. Plan the transition (rebuild + diff — F14.1)
    steps = step_planner.plan_transition(
        system_config, car_ports, initial_state, final_state
    )

    return ControlStepSequence(
        total_steps=len(steps),
        steps=steps,
        initial_state=initial_state,
        warnings=warnings,
    )
