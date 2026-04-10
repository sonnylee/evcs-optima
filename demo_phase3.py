"""Phase 3 demo — MCUControl with borrow/return and conflict detection."""

from simulation.environment.simulation_engine import SimulationEngine
from simulation.utils.config_loader import (
    ConfigLoader,
    InitialVehiclePlacement,
    SimulationConfig,
    VehicleProfile,
)


def demo_single_vehicle():
    """One vehicle at O0 — borrows G2/G3, returns as demand drops."""
    print("=" * 60)
    print("SCENARIO 1: Single vehicle at O0 (borrow/return cycle)")
    print("=" * 60)
    config = ConfigLoader.load_default()
    engine = SimulationEngine(config)
    engine.run()
    engine.print_summary()
    _print_borrow_return_events(engine)


def demo_two_vehicles():
    """Two vehicles at O0 and O1 — each gets 125 kW, no borrowing."""
    print("=" * 60)
    print("SCENARIO 2: Two vehicles (O0 + O1) — no borrowing possible")
    print("=" * 60)
    profiles = ConfigLoader.load_csv()
    ct = profiles["2024 Tesla Cybertruck Cyberbeast (325 kW, optimized)"]
    config = SimulationConfig(
        dt=1.0,
        t_end=3600.0,
        num_mcus=1,
        vehicle_profiles=[ct],
        initial_vehicles=[
            InitialVehiclePlacement(ct.name, 0, 20.0, 80.0),
            InitialVehiclePlacement(ct.name, 1, 20.0, 80.0),
        ],
    )
    engine = SimulationEngine(config)
    engine.run()
    engine.print_summary()
    _print_borrow_return_events(engine)


def demo_staggered_arrival():
    """EV1 at O0 borrows G2/G3, then EV2 arrives at O1 after 60s — conflict!"""
    print("=" * 60)
    print("SCENARIO 3: Staggered arrival — conflict detection")
    print("=" * 60)
    profiles = ConfigLoader.load_csv()
    ct = profiles["2024 Tesla Cybertruck Cyberbeast (325 kW, optimized)"]

    # Start with only EV at O0
    config = SimulationConfig(
        dt=1.0,
        t_end=600.0,
        num_mcus=1,
        vehicle_profiles=[ct],
        initial_vehicles=[
            InitialVehiclePlacement(ct.name, 0, 20.0, 80.0),
        ],
    )
    engine = SimulationEngine(config)

    # Run for 60 steps (EV0 should borrow extra groups by then)
    tc = engine.time_controller
    dt = tc.dt
    for _ in range(60):
        for v in engine.vehicles:
            v.step(dt)
        for mcu in engine.mcu_controls:
            mcu.step(dt)
        engine.station.step(dt)
        engine._collect_snapshot()
        tc.tick()

    # Print state before second vehicle
    print("\n--- After 60s (before EV1 arrives) ---")
    mcu = engine.mcu_controls[0]
    for s in mcu._output_states:
        print(f"  O{s.output_local_idx}: interval={[s.interval_min, s.interval_max] if s.interval_min is not None else None}")
    print(f"  MA O0: {engine.station.module_assignment._matrix[0]}")
    print(f"  MA O1: {engine.station.module_assignment._matrix[1]}")

    # Add second vehicle at O1 — triggers conflict detection
    from simulation.modules.vehicle import Vehicle
    ev2 = Vehicle(
        vehicle_id="EV_1",
        battery_capacity_kwh=ct.battery_capacity_kwh,
        soc_power_curve=ct.soc_power_curve,
        initial_soc=30.0,
        target_soc=80.0,
    )
    board = engine.station.rectifier_board
    mcu.handle_vehicle_arrival(1)
    board.outputs[1].connect_vehicle(ev2)
    engine.vehicles.append(ev2)

    print("\n--- After EV1 arrival (conflict resolved) ---")
    for s in mcu._output_states:
        print(f"  O{s.output_local_idx}: interval={[s.interval_min, s.interval_max] if s.interval_min is not None else None}")
    print(f"  MA O0: {engine.station.module_assignment._matrix[0]}")
    print(f"  MA O1: {engine.station.module_assignment._matrix[1]}")

    # Continue simulation
    while not tc.is_finished():
        for v in engine.vehicles:
            v.step(dt)
        for m in engine.mcu_controls:
            m.step(dt)
        engine.station.step(dt)
        engine._collect_snapshot()
        tc.tick()

    print()
    engine.print_summary()
    _print_borrow_return_events(engine)


def _print_borrow_return_events(engine):
    """Print relay switching timeline."""
    events = engine.event_log.get_events()
    if not events:
        return
    print("Relay event timeline:")
    for e in events:
        print(f"  dt={e.dt_index:4d}  {e.relay_id:15s}  {e.from_state} -> {e.to_state}")
    print()


if __name__ == "__main__":
    demo_single_vehicle()
    print("\n")
    demo_two_vehicles()
    print("\n")
    demo_staggered_arrival()
