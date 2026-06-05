"""Anti-drift guard + smoke test for the exploration test-driver.

Two concerns, both Commit-1 DoD:

1. ``test_driver_matches_production`` — the ``ExplorationDriver`` must reproduce
   ``SimulationEngine._driver_loop`` tick-for-tick. We run one engine via
   production ``run()`` and an identical engine via the driver, then assert the
   resulting ``RelayEventLog`` (grouped per step) and final snapshot are
   equivalent. If production ``_driver_loop`` ever changes, this goes red,
   forcing the driver copy to be updated in lock-step — no silent divergence.

2. ``test_inject_and_quiescence`` — injecting one arrival onto an empty station
   and stepping the driver drives ``is_quiescent`` from False (settling) to True
   (settled), proving the driver + injector + detector compose.
"""
from __future__ import annotations

import asyncio

import pytest

from simulation.environment.simulation_engine import SimulationEngine
from simulation.utils.config_loader import (
    InitialVehiclePlacement,
    SimulationConfig,
    VehicleProfile,
)
from tests.algo_validation.helpers.arrive_inject import inject_arrive
from tests.algo_validation.helpers.async_driver import ExplorationDriver
from tests.algo_validation.helpers.quiescence import is_quiescent

_FLAT_250 = [(0.0, 250.0), (100.0, 250.0)]


def _guard_config() -> SimulationConfig:
    """4-MCU (async path) with one EV on output 0: small battery so it
    completes + departs within a few dozen ticks, exercising arrival, borrow,
    and the §11 departure open-sequence in a single short run."""
    return SimulationConfig(
        dt=1.0,
        t_end=1e9,
        num_mcus=4,
        vehicle_profiles=[
            VehicleProfile(
                name="guard_ev",
                battery_capacity_kwh=5.0,
                soc_power_curve=_FLAT_250,
            )
        ],
        initial_vehicles=[
            InitialVehiclePlacement(
                vehicle_profile_name="guard_ev",
                output_index=0,
                initial_soc=30.0,
                target_soc=90.0,
            )
        ],
    )


def _events_by_step(engine: SimulationEngine) -> dict[int, list[tuple[str, str, str]]]:
    """RelayEventLog grouped per step, each step's events sorted — robust to any
    intra-step ordering nondeterminism between the two actor runs."""
    by_step: dict[int, list[tuple[str, str, str]]] = {}
    for e in engine.event_log.get_events():
        by_step.setdefault(e.dt_index, []).append((e.relay_id, e.from_state, e.to_state))
    return {k: sorted(v) for k, v in by_step.items()}


async def _drive_via_explorer(engine: SimulationEngine) -> None:
    """Mirror _driver_loop's structure exactly: while-not-finished → body →
    break on all-charging-complete (simulation_engine.py:166 + 195-196)."""
    driver = ExplorationDriver(engine)
    await driver.start_actors()
    try:
        tc = engine.time_controller
        while not tc.is_finished():
            await driver.tick()
            if engine._all_charging_complete():
                break
    finally:
        await driver.stop_actors()


def test_driver_matches_production() -> None:
    prod = SimulationEngine(_guard_config(), scenario_name="guard_prod")
    prod.run()  # asyncio.run internally — run OUTSIDE any event loop

    explo = SimulationEngine(_guard_config(), scenario_name="guard_explo")
    asyncio.run(_drive_via_explorer(explo))

    # Same number of steps reached.
    assert explo.time_controller.step_index == prod.time_controller.step_index

    # Same relay-event sequence (per-step, order-insensitive within a step).
    assert _events_by_step(explo) == _events_by_step(prod)
    assert len(explo.event_log) == len(prod.event_log)

    # Same snapshot stream length + identical terminal hardware state.
    prod_snaps = prod.snapshots.all()
    explo_snaps = explo.snapshots.all()
    assert len(explo_snaps) == len(prod_snaps)
    assert prod_snaps, "guard scenario should produce snapshots"
    for field in ("step_index", "station", "mcu_controls", "violations"):
        assert explo_snaps[-1][field] == prod_snaps[-1][field], f"mismatch in {field}"


@pytest.mark.asyncio
async def test_inject_and_quiescence() -> None:
    # Empty 4-MCU station (no initial vehicles, no traffic simulator).
    engine = SimulationEngine(
        SimulationConfig(dt=1.0, t_end=1e9, num_mcus=4), scenario_name="quiescence"
    )
    driver = ExplorationDriver(engine)
    await driver.start_actors()
    try:
        # Empty station starts settled.
        assert is_quiescent(engine) is True

        # Inject one low-SOC arrival on output 0 with a large battery so it
        # reaches a steady charging plateau (and stays there) within budget.
        inject_arrive(engine, output_idx=0, soc_level="low", max_kw=250, battery_kwh=75.0)
        # Pending close indicators are now set → no longer quiescent.
        assert is_quiescent(engine) is False

        observed: list[bool] = []
        for _ in range(120):
            await driver.tick()
            observed.append(is_quiescent(engine))
            if engine._all_charging_complete():
                break
    finally:
        await driver.stop_actors()

    # Saw the settling transient (False) and reached settled steady state (True),
    # with a False strictly before the final True → a real False→True transition.
    assert any(q is False for q in observed), "never observed the settling transient"
    assert observed[-1] is True, "did not settle into a quiescent steady state"
    first_true = observed.index(True)
    assert any(q is False for q in observed[:first_true]) or observed[0] is False
