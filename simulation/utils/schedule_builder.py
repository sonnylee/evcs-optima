"""Build SimulationConfig + ArrivalEvent schedule from SimParams."""
from __future__ import annotations

import random

from simulation.modules.traffic_simulator import ArrivalEvent
from simulation.utils.config_loader import (
    DEFAULT_VEHICLE_NAME,
    ConfigLoader,
    SimulationConfig,
    VehicleProfile,
)
from simulation.utils.interactive_prompt import SimParams


def _pick_int(rng: random.Random, mode: str, lo: int, hi: int) -> int:
    if mode == "fixed":
        return lo
    return rng.randint(lo, hi)


def build_config_and_schedule(
    params: SimParams,
    num_outputs: int,
    t_end: float = 7200.0,
    num_mcus: int = 4,
    dt: float = 1.0,
    seed: int | None = None,
) -> tuple[SimulationConfig, list[ArrivalEvent], dict[str, VehicleProfile]]:
    rng = random.Random(seed)
    profiles = ConfigLoader.load_csv()
    cybertruck = profiles[DEFAULT_VEHICLE_NAME]

    if params.arrival_order == "seq":
        order = list(range(num_outputs))
    else:
        order = list(range(num_outputs))
        rng.shuffle(order)

    schedule: list[ArrivalEvent] = []
    t = 0.0
    for i, out_idx in enumerate(order):
        if i > 0:
            gap_min = _pick_int(
                rng, params.interval_mode, params.interval_min, params.interval_max
            )
            t += gap_min * 60.0

        initial_soc = _pick_int(
            rng, params.soc_init_mode, params.soc_init_lo, params.soc_init_hi
        )
        tgt_lo = max(params.soc_tgt_lo, initial_soc + 1)
        tgt_hi = max(params.soc_tgt_hi, tgt_lo)
        if params.soc_tgt_mode == "fixed":
            target_soc = max(params.soc_tgt_lo, initial_soc + 1)
        else:
            target_soc = rng.randint(tgt_lo, tgt_hi)

        schedule.append(ArrivalEvent(
            arrival_time=t,
            output_index=out_idx,
            vehicle_profile_name=cybertruck.name,
            initial_soc=float(initial_soc),
            target_soc=float(target_soc),
            vehicle_id=f"EV{i+1}",
        ))

    config = SimulationConfig(
        dt=dt,
        t_end=t_end,
        num_mcus=num_mcus,
        vehicle_profiles=[cybertruck],
        initial_vehicles=[],
    )
    return config, schedule, {cybertruck.name: cybertruck}
