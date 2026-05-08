"""Phase 0 Spike — FR-09 reactive feasibility test against SimulationEngine.

Verifies whether the existing time-driven ``simulation/SimulationEngine`` can
converge to a stable state under static topologies (SPEC §16, 14 scenarios)
and a handful of demand-changing scenarios.

Per spike directive: NO modifications to production code. Read-only use of
the engine. Records observed behavior; does not fix issues found.

Run with: ``pytest tests/integration/test_engine_for_web_spike.py -v -m spike``
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from simulation.communication.messages import Stop, Tick
from simulation.environment.simulation_engine import SimulationEngine
from simulation.hardware.relay import RelayState
from simulation.modules.mcu_control import output_min_guarantee_kw
from simulation.modules.vehicle import Vehicle, VehicleState
from simulation.utils.config_loader import (
    InitialVehiclePlacement,
    SimulationConfig,
    VehicleProfile,
)

NUM_MCUS = 4
SYSTEM_TOTAL_KW = 250 * NUM_MCUS  # 4 × 250 = 1000
SPIKE_PROFILE_NAME = "spike_static"
DEFAULT_INITIAL_SOC = 50.0
DEFAULT_TARGET_SOC = 99.0
DEFAULT_BATTERY_KWH = 75.0
DEFAULT_DT = 1.0
DEFAULT_T_END = 1e9  # we drive ticks ourselves; never let the engine end
STABLE_WINDOW = 5
TIMEOUT_TICKS = 200


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _flat_curve(kw: float) -> list[tuple[float, float]]:
    """SOC-power curve where max_require stays constant for any SOC."""
    return [(0.0, float(kw)), (100.0, float(kw))]


def build_spike_engine(
    arrivals: list[tuple[int, int]],
    *,
    consecutive_threshold: int = 3,
    initial_soc: float = DEFAULT_INITIAL_SOC,
    target_soc: float = DEFAULT_TARGET_SOC,
) -> SimulationEngine:
    """Build a 4-MCU ``SimulationEngine`` with the given (output_idx, max_kw) arrivals.

    Each entry connects a static-demand vehicle to that output. ``arrivals``
    may be empty for a no-vehicle engine.
    """
    profiles: dict[float, VehicleProfile] = {}
    placements: list[InitialVehiclePlacement] = []
    for output_idx, max_kw in arrivals:
        key = float(max_kw)
        name = f"{SPIKE_PROFILE_NAME}_{int(key)}"
        if key not in profiles:
            profiles[key] = VehicleProfile(
                name=name,
                battery_capacity_kwh=DEFAULT_BATTERY_KWH,
                soc_power_curve=_flat_curve(key),
            )
        placements.append(
            InitialVehiclePlacement(
                vehicle_profile_name=name,
                output_index=output_idx,
                initial_soc=initial_soc,
                target_soc=target_soc,
            )
        )
    cfg = SimulationConfig(
        dt=DEFAULT_DT,
        t_end=DEFAULT_T_END,
        num_mcus=NUM_MCUS,
        vehicle_profiles=list(profiles.values()),
        initial_vehicles=placements,
        consecutive_threshold=consecutive_threshold,
    )
    return SimulationEngine(cfg, traffic_simulator=None, scenario_name="spike")


# ─────────────────────────────────────────────────────────────────────
# Convergence runner — drives the engine without ``engine.run()``.
# ─────────────────────────────────────────────────────────────────────
class SpikeRunner:
    """Drives the actor loop manually so we can observe per-tick state and
    detect convergence as: no new ``RelayEvent`` for ``stable_window``
    consecutive ticks AND all ``pending_*`` phase counters cleared.
    """

    def __init__(self, engine: SimulationEngine):
        self.engine = engine
        self._actor_tasks: list = []

    async def __aenter__(self) -> "SpikeRunner":
        import asyncio
        self._actor_tasks = [
            asyncio.create_task(m.run()) for m in self.engine.mcu_controls
        ]
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        import asyncio
        for m in self.engine.mcu_controls:
            await m.send(Stop())
        await asyncio.gather(*self._actor_tasks, return_exceptions=True)

    def _all_pending_clear(self) -> bool:
        for mcu in self.engine.mcu_controls:
            for s in mcu._output_states:
                if (
                    s.pending_intergroup_close != 0
                    or s.pending_output_relay_close != 0
                    or s.pending_intergroup_open != 0
                    or s.pending_output_relay_open != 0
                ):
                    return False
        return True

    async def step_once(self) -> None:
        import asyncio
        engine = self.engine
        tc = engine.time_controller
        dt = tc.dt
        for mcu in engine.mcu_controls:
            mcu._step_index = tc.step_index
        for vehicle in engine.vehicles:
            vehicle.step(dt)
        engine._trigger_departures()
        done_events = [asyncio.Event() for _ in engine.mcu_controls]
        for mcu, ev in zip(engine.mcu_controls, done_events):
            await mcu.send(Tick(dt=dt, step_index=tc.step_index, done=ev))
        await asyncio.gather(*(e.wait() for e in done_events))
        await asyncio.sleep(0)
        engine.station.step(dt)
        tc.tick()

    async def run_until_stable(
        self,
        *,
        timeout_ticks: int = TIMEOUT_TICKS,
        stable_window: int = STABLE_WINDOW,
    ) -> dict[str, Any]:
        start = time.perf_counter()
        baseline = len(self.engine.event_log)
        last = baseline
        stable_streak = 0
        ticks = 0
        converged = False
        for _ in range(timeout_ticks):
            await self.step_once()
            ticks += 1
            cur = len(self.engine.event_log)
            if cur == last:
                stable_streak += 1
                if stable_streak >= stable_window and self._all_pending_clear():
                    converged = True
                    break
            else:
                stable_streak = 0
            last = cur
        wall_ms = (time.perf_counter() - start) * 1000.0
        return {
            "converged": converged,
            "tick_count": ticks,
            "wall_time_ms": round(wall_ms, 2),
            "event_count": len(self.engine.event_log) - baseline,
        }


# ─────────────────────────────────────────────────────────────────────
# Invariant checks
# ─────────────────────────────────────────────────────────────────────
def assert_engine_invariants(engine: SimulationEngine) -> None:
    """Five system-wide invariants — see report §"Invariant verification"."""
    # 1) No double-assignment. Per-board MAs cover a 3-MCU window; the same
    #    physical group may appear in multiple MAs (mirror-sync), but every
    #    board that has an opinion must agree on the owner.
    seen: dict[int, int] = {}
    for board in engine.station.boards:
        ma = board.module_assignment
        for abs_g in range(NUM_MCUS * 4):
            owner = ma.get_owner(abs_g)
            if owner is None:
                continue
            prev = seen.get(abs_g)
            if prev is not None and prev != owner:
                raise AssertionError(
                    f"group {abs_g} double-assigned: board {board.mcu_id} "
                    f"says owner={owner}, earlier board says owner={prev}"
                )
            seen[abs_g] = owner

    # 2) Every active output (relay closed + vehicle present) has ≥ per-Output
    # SPEC §11 minimum guarantee (default `[50,75,75,50]` config = 125 kW).
    for i, output in enumerate(engine._all_outputs):
        mcu_idx, local_idx = i // 2, i % 2
        board = engine.station.boards[mcu_idx]
        out_relay = board.output_relays[local_idx]
        if (
            out_relay.state == RelayState.CLOSED
            and output.connected_vehicle is not None
        ):
            floor = output_min_guarantee_kw(board.module_powers, local_idx)
            if output.available_power_kw + 1e-6 < floor:
                raise AssertionError(
                    f"Output {i}: closed with available={output.available_power_kw} < {floor} kW"
                )

    # 3) Sum of available across active outputs ≤ system total.
    total_active = 0.0
    for i, o in enumerate(engine._all_outputs):
        out_relay = engine.station.boards[i // 2].output_relays[i % 2]
        if out_relay.state == RelayState.CLOSED and o.connected_vehicle is not None:
            total_active += o.available_power_kw
    if total_active > SYSTEM_TOTAL_KW + 0.01:
        raise AssertionError(
            f"Total active available {total_active} kW > system total {SYSTEM_TOTAL_KW} kW"
        )

    # 4) All pending_* phase counters cleared.
    for mcu in engine.mcu_controls:
        for s in mcu._output_states:
            if (
                s.pending_intergroup_close != 0
                or s.pending_output_relay_close != 0
                or s.pending_intergroup_open != 0
                or s.pending_output_relay_open != 0
            ):
                raise AssertionError(
                    f"MCU{mcu._mcu_id} O{s.output_local_idx} pending phases: "
                    f"close({s.pending_intergroup_close},{s.pending_output_relay_close}) "
                    f"open({s.pending_intergroup_open},{s.pending_output_relay_open})"
                )


# ─────────────────────────────────────────────────────────────────────
# Static topology scenarios — SPEC §16 14-scenario matrix
# ─────────────────────────────────────────────────────────────────────
SPEC_SCENARIOS: list[tuple[str, str, list[int]]] = [
    ("01", "(3,1,0)", [0]),
    ("02", "(2,2,0)", [0, 2]),
    ("03", "(3,0,1)", [0, 1]),
    ("04", "(1,3,0)", [0, 2, 4]),
    ("05", "(2,1,1)", [0, 1, 2]),
    ("06", "(0,4,0)", [0, 2, 4, 6]),
    ("07", "(1,2,1)", [0, 1, 2, 4]),
    ("08", "(2,0,2)", [0, 1, 2, 3]),
    ("09", "(0,3,1)", [0, 1, 2, 4, 6]),
    ("10", "(1,1,2)", [0, 1, 2, 3, 4]),
    ("11", "(0,2,2)", [0, 1, 2, 3, 4, 6]),
    ("12", "(1,0,3)", [0, 1, 2, 3, 4, 5]),
    ("13", "(0,1,3)", [0, 1, 2, 3, 4, 5, 6]),
    ("14", "(0,0,4)", [0, 1, 2, 3, 4, 5, 6, 7]),
]


# Module-level result accumulator. Tests append; the session-scoped
# autouse fixture below dumps the data at the end so the report can be
# generated by re-running with -s and grepping for the JSON markers.
SPIKE_RESULTS: dict[str, dict[str, Any]] = {}


def _record(name: str, **fields: Any) -> None:
    SPIKE_RESULTS[name] = fields


@pytest.fixture(scope="session", autouse=True)
def _emit_spike_results():
    yield
    if not SPIKE_RESULTS:
        return
    print("\n===== SPIKE RESULTS =====")
    for name, info in SPIKE_RESULTS.items():
        print(f"SPIKE_RESULT::{name}::{json.dumps(info, default=str)}")
    print("===== END SPIKE RESULTS =====")


def _make_static_test(scenario_id: str, label: str, on_outputs: list[int]):
    @pytest.mark.spike
    @pytest.mark.asyncio
    async def _test():
        arrivals = [(o, 125) for o in on_outputs]
        engine = build_spike_engine(arrivals)
        async with SpikeRunner(engine) as r:
            result = await r.run_until_stable(timeout_ticks=TIMEOUT_TICKS)

        # Capture invariant + active-output checks separately so the report
        # records what failed without short-circuiting.
        inv_ok, inv_err = True, ""
        try:
            assert_engine_invariants(engine)
        except AssertionError as e:
            inv_ok, inv_err = False, str(e)

        active_ok, active_err = True, ""
        try:
            on_set = set(on_outputs)
            for i, output in enumerate(engine._all_outputs):
                if i in on_set:
                    if output.connected_vehicle is None:
                        raise AssertionError(f"Output {i} expected ON but no vehicle")
                    mcu_idx, local_idx = i // 2, i % 2
                    board = engine.station.boards[mcu_idx]
                    floor = output_min_guarantee_kw(board.module_powers, local_idx)
                    if output.available_power_kw + 1e-6 < floor:
                        raise AssertionError(
                            f"Output {i}: available={output.available_power_kw} < {floor} kW"
                        )
                else:
                    if output.connected_vehicle is not None:
                        raise AssertionError(f"Output {i} expected OFF but vehicle attached")
        except AssertionError as e:
            active_ok, active_err = False, str(e)

        _record(
            f"test_spec_{scenario_id}",
            label=label,
            on_outputs=on_outputs,
            **result,
            invariants_ok=inv_ok,
            actives_ok=active_ok,
            err=inv_err or active_err,
        )

        # Pytest assertions last so the recording always happens.
        assert result["converged"], (
            f"did not converge in {result['tick_count']} ticks "
            f"(events={result['event_count']})"
        )
        assert inv_ok, f"invariant violation: {inv_err}"
        assert active_ok, f"active-output check failed: {active_err}"

    _test.__name__ = f"test_spec_{scenario_id}"
    _test.__doc__ = f"SPEC §16 scenario {scenario_id} {label}, ON={on_outputs}"
    return _test


# Generate 14 static-scenario tests at module load.
for _sid, _label, _on in SPEC_SCENARIOS:
    globals()[f"test_spec_{_sid}"] = _make_static_test(_sid, _label, _on)


# ─────────────────────────────────────────────────────────────────────
# Dynamic scenarios
# ─────────────────────────────────────────────────────────────────────
def _set_curve(vehicle: Vehicle, kw: float) -> None:
    vehicle.soc_power_curve = sorted(_flat_curve(kw), key=lambda p: p[0])
    vehicle.max_require_power_kw = float(kw)


def _settle_segment(
    runner: SpikeRunner, label: str
) -> dict[str, Any]:
    """Run until stable + check invariants. Bundles result for reporting."""
    async def _run():
        return await runner.run_until_stable(timeout_ticks=TIMEOUT_TICKS)
    # caller is async; we just dispatch directly
    return _run  # placeholder; callers will await the coroutine helper below


async def _segment(
    runner: SpikeRunner, label: str
) -> dict[str, Any]:
    res = await runner.run_until_stable(timeout_ticks=TIMEOUT_TICKS)
    seg = {"phase": label, **res}
    try:
        assert_engine_invariants(runner.engine)
        seg["invariants_ok"] = True
        seg["err"] = ""
    except AssertionError as e:
        seg["invariants_ok"] = False
        seg["err"] = str(e)
    return seg


@pytest.mark.spike
@pytest.mark.asyncio
async def test_dyn_01_grow_shrink():
    """O0 demand 0 → 125 → 250 → 125 → 0. Run-until-stable + invariants per step."""
    segments: list[dict[str, Any]] = []

    # 0 → 125: build engine with the initial arrival.
    engine = build_spike_engine([(0, 125)])
    async with SpikeRunner(engine) as r:
        segments.append(await _segment(r, "0->125"))

        v = engine._all_outputs[0].connected_vehicle
        assert v is not None, "expected vehicle on O0 after init"

        # 125 → 250: bump max via curve mutation (no need to re-arrive).
        _set_curve(v, 250.0)
        segments.append(await _segment(r, "125->250"))

        # 250 → 125: drop max via curve mutation.
        _set_curve(v, 125.0)
        segments.append(await _segment(r, "250->125"))

        # 125 → 0: trigger departure (no native "demand=0" path in core).
        v.state = VehicleState.COMPLETE
        segments.append(await _segment(r, "125->0(depart)"))

    converged = all(s["converged"] for s in segments)
    invariants = all(s["invariants_ok"] for s in segments)
    _record(
        "test_dyn_01_grow_shrink",
        segments=segments,
        cumulative_ticks=sum(s["tick_count"] for s in segments),
        cumulative_wall_ms=round(sum(s["wall_time_ms"] for s in segments), 2),
        cumulative_events=sum(s["event_count"] for s in segments),
        converged_all=converged,
        invariants_all=invariants,
    )
    assert converged, "at least one segment failed to converge"
    assert invariants, "at least one segment violated invariants"


@pytest.mark.spike
@pytest.mark.asyncio
async def test_dyn_02_progressive_fill():
    """SPEC §16 scenario 1 → 14, rebuilding the engine for each step.

    The simulation core has no API to attach extra vehicles to a live
    engine in a SPEC §11-correct way, so each step rebuilds. Cumulative
    metrics are logged for the report.
    """
    segments: list[dict[str, Any]] = []
    converged_all = True
    invariants_all = True
    for sid, label, on in SPEC_SCENARIOS:
        engine = build_spike_engine([(o, 125) for o in on])
        async with SpikeRunner(engine) as r:
            res = await r.run_until_stable(timeout_ticks=TIMEOUT_TICKS)
        inv_ok, inv_err = True, ""
        try:
            assert_engine_invariants(engine)
        except AssertionError as e:
            inv_ok, inv_err = False, str(e)
        seg = {
            "scenario": sid,
            "label": label,
            "on_outputs": on,
            **res,
            "invariants_ok": inv_ok,
            "err": inv_err,
        }
        segments.append(seg)
        converged_all = converged_all and res["converged"]
        invariants_all = invariants_all and inv_ok

    _record(
        "test_dyn_02_progressive_fill",
        segments=segments,
        cumulative_ticks=sum(s["tick_count"] for s in segments),
        cumulative_wall_ms=round(sum(s["wall_time_ms"] for s in segments), 2),
        cumulative_events=sum(s["event_count"] for s in segments),
        converged_all=converged_all,
        invariants_all=invariants_all,
    )
    assert converged_all, "progressive-fill failed to converge at some step"
    assert invariants_all, "progressive-fill violated invariants at some step"


@pytest.mark.spike
@pytest.mark.asyncio
async def test_dyn_03_engine_reuse():
    """Same engine, demand sequence on O0: 100 → 200 → 100 → 0 → 150."""
    sequence = [100, 200, 100, 0, 150]
    segments: list[dict[str, Any]] = []
    engine = build_spike_engine([(0, sequence[0])])
    async with SpikeRunner(engine) as r:
        segments.append(await _segment(r, f"init->{sequence[0]}"))

        for prev, target in zip(sequence, sequence[1:]):
            v = engine._all_outputs[0].connected_vehicle
            if target == 0:
                if v is not None:
                    v.state = VehicleState.COMPLETE
            elif v is None:
                # Re-arrival path after a departure: connect a fresh vehicle.
                profile = engine.config.vehicle_profiles[0]
                vehicle = Vehicle(
                    vehicle_id="EV_0_reuse",
                    battery_capacity_kwh=profile.battery_capacity_kwh,
                    soc_power_curve=_flat_curve(target),
                    initial_soc=DEFAULT_INITIAL_SOC,
                    target_soc=DEFAULT_TARGET_SOC,
                )
                engine._all_outputs[0].connect_vehicle(vehicle)
                engine.vehicles.append(vehicle)
                engine.mcu_controls[0].handle_vehicle_arrival(0)
            else:
                _set_curve(v, float(target))
            segments.append(await _segment(r, f"{prev}->{target}"))

    converged = all(s["converged"] for s in segments)
    invariants = all(s["invariants_ok"] for s in segments)
    _record(
        "test_dyn_03_engine_reuse",
        segments=segments,
        cumulative_ticks=sum(s["tick_count"] for s in segments),
        cumulative_wall_ms=round(sum(s["wall_time_ms"] for s in segments), 2),
        cumulative_events=sum(s["event_count"] for s in segments),
        converged_all=converged,
        invariants_all=invariants,
    )
    assert converged, "engine-reuse failed to converge at some step"
    assert invariants, "engine-reuse violated invariants at some step"


@pytest.mark.spike
@pytest.mark.asyncio
async def test_dyn_04_overload():
    """4 outputs × 600 kW demand vs 1000 kW total capacity.

    Pass criterion: no livelock — event count must not keep growing every
    tick. We sample event count across the whole 200-tick window and assert
    that the last 50 ticks added < 100 events.
    """
    arrivals = [(0, 600), (1, 600), (2, 600), (3, 600)]
    engine = build_spike_engine(arrivals)

    pre_count = len(engine.event_log)
    samples: list[int] = []
    start = time.perf_counter()
    async with SpikeRunner(engine) as r:
        for _ in range(TIMEOUT_TICKS):
            await r.step_once()
            samples.append(len(engine.event_log))
    wall_ms = (time.perf_counter() - start) * 1000.0

    delta_total = samples[-1] - pre_count
    last_50 = samples[-50:]
    last_growth = last_50[-1] - last_50[0]

    inv_ok, inv_err = True, ""
    try:
        assert_engine_invariants(engine)
    except AssertionError as e:
        inv_ok, inv_err = False, str(e)

    info = {
        "tick_count": TIMEOUT_TICKS,
        "wall_time_ms": round(wall_ms, 2),
        "total_events_added": delta_total,
        "events_in_last_50_ticks": last_growth,
        "samples_first_10": samples[:10],
        "samples_last_10": samples[-10:],
        "invariants_ok": inv_ok,
        "err": inv_err,
    }
    _record("test_dyn_04_overload", **info)

    assert last_growth < 100, (
        f"likely livelock: {last_growth} events added in last 50 ticks; "
        f"samples last 10 = {samples[-10:]}"
    )
