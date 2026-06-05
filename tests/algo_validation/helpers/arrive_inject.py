"""``inject_arrive`` — synchronous low-level arrival injection (D-14 / C2).

``TrafficSimulator`` cannot inject mid-run (its ``__init__`` fixes the schedule
once, ``traffic_simulator.py:41``), so the harness drives arrivals through the
same three low-level calls the engine itself uses for its initial connections
(``simulation_engine.py:60-104``):

    output.connect_vehicle(v)   # claim anchor groups (Output side)
    engine.vehicles.append(v)   # register for stepping
    mcu.handle_vehicle_arrival(local_idx)   # authoritative assign + relay close

C2: the owning MCU's clock is aligned to the sim clock *before* the three steps,
exactly as ``_driver_loop`` does at the top of each tick
(``simulation_engine.py:173-174``). Without this, the relay switches fired by
``handle_vehicle_arrival`` get stamped with a stale step index and end up
orphaned in the ``RelayEventLog``.

D-1: SOC level → representative initial SOC: low 15 / mid 55 / high 90 (%).
"""
from __future__ import annotations

from typing import Any

from simulation.modules.vehicle import Vehicle

# D-1 representative initial-SOC values per bucket (low 0–30 / mid 30–80 /
# high 80–100). High (90) with the default target (90) departs near-immediately
# — that is the system's real behaviour for a near-full arrival, exercised on
# purpose; callers wanting the EV to engage should pass a higher target_soc.
_SOC_BY_LEVEL = {"low": 15.0, "mid": 55.0, "high": 90.0}

_DEFAULT_BATTERY_KWH = 75.0
_DEFAULT_TARGET_SOC = 90.0
_DEFAULT_MAX_KW = 250


def inject_arrive(
    engine: Any,
    output_idx: int,
    soc_level: str,
    *,
    max_kw: int = _DEFAULT_MAX_KW,
    battery_kwh: float = _DEFAULT_BATTERY_KWH,
    target_soc: float = _DEFAULT_TARGET_SOC,
) -> Vehicle:
    """Inject an arrival at global ``output_idx`` with the given SOC bucket.

    Returns the created ``Vehicle``. Uses a flat power curve (constant
    ``max_kw``) mirroring the web layer's static placeholder, so demand is a
    fixed ceiling rather than a curve.
    """
    if soc_level not in _SOC_BY_LEVEL:
        raise ValueError(f"soc_level must be one of {sorted(_SOC_BY_LEVEL)}, got {soc_level!r}")

    mcu_idx = output_idx // 2
    local_idx = output_idx % 2
    mcu = engine.mcu_controls[mcu_idx]
    # C2: align the owning MCU's clock before the low-level steps.
    mcu._step_index = engine.time_controller.step_index

    initial_soc = _SOC_BY_LEVEL[soc_level]
    vehicle = Vehicle(
        vehicle_id=f"EV_o{output_idx}_s{engine.time_controller.step_index}",
        battery_capacity_kwh=battery_kwh,
        soc_power_curve=[(0.0, float(max_kw)), (100.0, float(max_kw))],
        initial_soc=initial_soc,
        target_soc=target_soc,
    )

    # Three low-level steps, in engine.__init__ order: connect → append → handle
    # (simulation_engine.py:69-70 then :104).
    engine._all_outputs[output_idx].connect_vehicle(vehicle)
    engine.vehicles.append(vehicle)
    mcu.handle_vehicle_arrival(local_idx)
    return vehicle
