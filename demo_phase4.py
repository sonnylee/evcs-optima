"""Phase 4 demo — Multi-MCU with cross-MCU borrow/return via asyncio+Queue."""

import sys

from simulation.environment.simulation_engine import SimulationEngine
from simulation.utils.config_loader import (
    ConfigLoader,
    InitialVehiclePlacement,
    SimulationConfig,
)


def demo_cross_mcu_borrow(num_mcus: int = 2):
    """Vehicle on MCU0/output1 borrows groups from MCU1 across the bridge."""
    print("=" * 60)
    print(f"SCENARIO: Cross-MCU borrow  (num_mcus={num_mcus})")
    print("=" * 60)
    profiles = ConfigLoader.load_csv()
    ct = profiles["2024 Tesla Cybertruck Cyberbeast (325 kW, optimized)"]

    # One hungry vehicle on MCU0 output 1 (anchored at G3, right neighbor = MCU1)
    config = SimulationConfig(
        dt=1.0,
        t_end=1800.0,
        num_mcus=num_mcus,
        vehicle_profiles=[ct],
        initial_vehicles=[
            InitialVehiclePlacement(ct.name, 1, 15.0, 80.0),
        ],
    )
    engine = SimulationEngine(config)
    engine.run()
    engine.print_summary()
    _print_events(engine, limit=40)


def demo_ring_topology():
    """4-MCU ring: vehicle on last MCU can borrow via wrap-around bridge."""
    print("=" * 60)
    print("SCENARIO: 4-MCU ring topology")
    print("=" * 60)
    profiles = ConfigLoader.load_csv()
    ct = profiles["2024 Tesla Cybertruck Cyberbeast (325 kW, optimized)"]
    config = SimulationConfig(
        dt=1.0,
        t_end=1200.0,
        num_mcus=4,
        vehicle_profiles=[ct],
        initial_vehicles=[
            # Output index 7 = MCU3 output 1 (anchored at G15; right neighbor = MCU0 via wrap)
            InitialVehiclePlacement(ct.name, 7, 15.0, 80.0),
        ],
    )
    engine = SimulationEngine(config)
    engine.run()
    engine.print_summary()
    _print_events(engine, limit=40)


def _print_events(engine, limit: int = 40):
    events = engine.event_log.get_events()
    if not events:
        print("(no relay events)")
        return
    print(f"Relay events ({len(events)} total, showing first {limit}):")
    for e in events[:limit]:
        print(f"  dt={e.dt_index:4d}  {e.relay_id:15s}  {e.from_state} -> {e.to_state}")
    print()


if __name__ == "__main__":
    mcus = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    if mcus >= 4:
        demo_ring_topology()
    else:
        demo_cross_mcu_borrow(num_mcus=mcus)
