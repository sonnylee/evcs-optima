"""Interactive entrypoint (SPEC §18) — prompt for parameters then run the sim."""
from __future__ import annotations

import os
import sys

from simulation.environment.simulation_engine import SimulationEngine
from simulation.modules.traffic_simulator import TrafficSimulator
from simulation.modules.vehicle_generator import VehicleGenerator
from simulation.utils.interactive_prompt import prompt_until_confirmed
from simulation.utils.schedule_builder import build_config_and_schedule


NUM_MCUS = 4
OUTPUTS_PER_MCU = 2
T_END = 7200.0


def main() -> int:
    params = prompt_until_confirmed()

    num_outputs = NUM_MCUS * OUTPUTS_PER_MCU
    config, schedule, profile_map = build_config_and_schedule(
        params,
        num_outputs=num_outputs,
        t_end=T_END,
        num_mcus=NUM_MCUS,
    )

    scenario_name = (
        f"Interactive_{params.arrival_order}_"
        f"int-{params.interval_mode}-{params.interval_min}-{params.interval_max}_"
        f"soc0-{params.soc_init_mode}-{params.soc_init_lo}-{params.soc_init_hi}_"
        f"soc1-{params.soc_tgt_mode}-{params.soc_tgt_lo}-{params.soc_tgt_hi}"
    )

    engine = SimulationEngine(config, scenario_name=scenario_name)
    generator = VehicleGenerator(profiles=profile_map)
    traffic = TrafficSimulator(
        generator=generator,
        outputs=engine._all_outputs,
        schedule=schedule,
    )
    engine.traffic_simulator = traffic

    print("\n-- Running simulation --")
    for ev in schedule:
        print(f"  t={ev.arrival_time:7.1f}s  O{ev.output_index+1}  "
              f"SOC {ev.initial_soc:.0f}->{ev.target_soc:.0f}  ({ev.vehicle_id})")

    engine.run()

    out_dir = os.path.join(
        os.path.dirname(__file__), "associate", "verify", "interactive"
    )
    os.makedirs(out_dir, exist_ok=True)
    csv_path = os.path.join(out_dir, "trace.csv")
    json_path = os.path.join(out_dir, "boundary.jsonl")
    ok = engine.export_csv(csv_path)
    engine.export_boundary_log(json_path)

    s = engine.validator.summary()
    print("\n-- Result --")
    print(f"  boundary_checks = {s['total_boundary_checks']}")
    print(f"  inconsistent    = {s['inconsistent']}")
    print(f"  violations      = {s['station_violations']}")
    print(f"  csv             = {csv_path} ({'ok' if ok else 'FAIL'})")
    print(f"  boundary log    = {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
