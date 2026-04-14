"""Phase 5 — Validator + Visualization over the 14 scenarios (SPEC §16).

Runs each scenario on a 4-MCU ring, validates boundary consistency
(SPEC §9), and exports the per-scenario trace CSV (SPEC §17) plus the
boundary JSON log under `associate/verify/`.
"""
from __future__ import annotations

import os
import sys

from simulation.environment.simulation_engine import SimulationEngine
from simulation.modules.traffic_simulator import ArrivalEvent, TrafficSimulator
from simulation.modules.vehicle_generator import VehicleGenerator
from simulation.utils.config_loader import ConfigLoader, SimulationConfig


# 14 scenarios per SPEC §16 — tuples of (ON count per MCU: M1, M2, M3, M4)
# encoded as which outputs are ON for each MCU (1 => O1 only, 2 => O1+O2, 0 => none)
SCENARIOS: list[tuple[str, tuple[int, int, int, int]]] = [
    ("01_(3,1,0)", (1, 0, 0, 0)),
    ("02_(2,2,0)", (1, 1, 0, 0)),
    ("03_(3,0,1)", (2, 0, 0, 0)),
    ("04_(1,3,0)", (1, 1, 1, 0)),
    ("05_(2,1,1)", (2, 1, 0, 0)),
    ("06_(0,4,0)", (1, 1, 1, 1)),
    ("07_(1,2,1)", (2, 1, 1, 0)),
    ("08_(2,0,2)", (2, 2, 0, 0)),
    ("09_(0,3,1)", (2, 1, 1, 1)),
    ("10_(1,1,2)", (2, 2, 1, 0)),
    ("11_(0,2,2)", (2, 2, 1, 1)),
    ("12_(1,0,3)", (2, 2, 2, 0)),
    ("13_(0,1,3)", (2, 2, 2, 1)),
    ("14_(0,0,4)", (2, 2, 2, 2)),
]

NUM_MCUS = 4
DT = 1.0
T_END = 7200.0  # 2h hard cap; scenarios stop early when all EVs reach target SOC


def _scenario_label(counts: tuple[int, ...]) -> str:
    parts = []
    for m, c in enumerate(counts, start=1):
        if c == 0:
            parts.append(f"MCU{m}(OFF)")
        elif c == 1:
            parts.append(f"MCU{m}(O1:ON, O2:OFF)")
        else:
            parts.append(f"MCU{m}(O1:ON, O2:ON)")
    return "; ".join(parts)


def _build_schedule(counts: tuple[int, ...], profile_name: str) -> list[ArrivalEvent]:
    schedule: list[ArrivalEvent] = []
    for mcu, c in enumerate(counts):
        base_output = mcu * 2
        for slot in range(c):
            schedule.append(ArrivalEvent(
                arrival_time=0.0,
                output_index=base_output + slot,
                vehicle_profile_name=profile_name,
                initial_soc=20.0,
                target_soc=80.0,
                vehicle_id=f"M{mcu+1}.EV{slot+1}",
            ))
    return schedule


def run_scenario(name: str, counts: tuple[int, ...], out_dir: str) -> dict:
    profiles = ConfigLoader.load_csv()
    ct_name = "2024 Tesla Cybertruck Cyberbeast (325 kW, optimized)"
    ct = profiles[ct_name]

    config = SimulationConfig(
        dt=DT,
        t_end=T_END,
        num_mcus=NUM_MCUS,
        vehicle_profiles=[ct],
        initial_vehicles=[],  # TrafficSimulator handles placement
    )

    generator = VehicleGenerator(profiles={ct.name: ct})
    scenario_header = f"Scenario_{name}: {_scenario_label(counts)}"

    engine = SimulationEngine(config, scenario_name=scenario_header)
    all_outputs = engine._all_outputs

    traffic = TrafficSimulator(
        generator=generator,
        outputs=all_outputs,
        schedule=_build_schedule(counts, ct.name),
    )
    engine.traffic_simulator = traffic

    engine.run()

    csv_path = os.path.join(out_dir, f"scenario_{name}.csv")
    json_path = os.path.join(out_dir, f"scenario_{name}_boundary.jsonl")

    ok = engine.export_csv(csv_path)
    engine.export_boundary_log(json_path)

    summary = engine.validator.summary()
    summary["csv_written"] = ok
    summary["csv_path"] = csv_path
    summary["scenario"] = name
    summary["active_outputs"] = sum(counts)
    return summary


def main() -> int:
    out_dir = os.path.join(
        os.path.dirname(__file__), "associate", "verify", "scenarios"
    )
    os.makedirs(out_dir, exist_ok=True)

    filter_arg = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 68)
    print("Phase 5 — Validation across 14 scenarios (SPEC §16)")
    print(f"Output dir: {out_dir}")
    print("=" * 68)

    results = []
    for name, counts in SCENARIOS:
        if filter_arg and filter_arg not in name:
            continue
        print(f"\n[{name}]  active outputs = {sum(counts)}")
        try:
            res = run_scenario(name, counts, out_dir)
            results.append(res)
            print(f"  boundary_checks={res['total_boundary_checks']}  "
                  f"inconsistent={res['inconsistent']}  "
                  f"violations={res['station_violations']}  "
                  f"csv_ok={res['csv_written']}")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            results.append({"scenario": name, "error": str(e)})

    print("\n" + "=" * 68)
    print("Summary")
    print("=" * 68)
    for r in results:
        if "error" in r:
            print(f"  {r['scenario']:14s}  ERROR  {r['error']}")
        else:
            status = "OK" if r["csv_written"] and r["inconsistent"] == 0 and r["station_violations"] == 0 else "WARN"
            print(f"  {r['scenario']:14s}  {status:4s}  "
                  f"outputs={r['active_outputs']}  "
                  f"boundary={r['inconsistent']}/{r['total_boundary_checks']}  "
                  f"violations={r['station_violations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
