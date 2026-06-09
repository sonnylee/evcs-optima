"""Exploration test — arrive-driven + passive-depart, dual-army validation.

Main loop (spec §7 skeleton): pick a coverage-directed arrival, inject it via
the low-level API, then drive the ``ExplorationDriver`` tick-by-tick. The
``on_tick`` hook runs the per-tick army every step and, on the rising edge of
quiescence, records coverage and runs the steady-state army. Departures are
entirely system-driven (never injected). Termination is spec §3.4.

Pass criteria (spec §9): every per-tick check and every steady check PASS —
they raise ``AssertionError`` in-place, so reaching ``tracker.report()`` means
all armies held. Coverage is observational, never a gate.

F1-b: arrivals alternate between high demand (250 kW, full interval, exercises
borrow + departure inter-group opens) and low demand (50 kW). A low-demand EV's
interval shrinks to its single anchor *while charging*, dynamically opening the
anchor inter-group relay (R_01/R_23) — the case decision 2 was blind to. The
report prints N = how many such dynamic-open events were observed (must be > 0,
else A1 / the inter-group ordering checks are vacuous).

Runtime: the spec's 24 h / 86,400-step ceiling is the production target; this CI
test uses a far smaller step budget (``_MAX_STEPS``) and relies on the
stagnation terminator. The reduction is logged in the report (no silent cap).
"""
from __future__ import annotations

import os

from simulation.environment.simulation_engine import SimulationEngine
from tests.algo_validation.conftest import EPSILON, SEED
from tests.algo_validation.helpers.arrive_inject import inject_arrive
from tests.algo_validation.helpers.async_driver import ExplorationDriver
from tests.algo_validation.helpers.coverage_tracker import CoverageTracker
from tests.algo_validation.helpers.quiescence import is_quiescent
from tests.algo_validation.helpers.reuse_adapters import read_state_from_snapshot
from tests.algo_validation.helpers.steady_checks import run_steady_checks
from tests.algo_validation.helpers.tick_checks import TickChecks

# Termination (spec §3.4). _MAX_STEPS is the CI budget; the spec target is
# 86,400 (24 h). _COVERAGE_TARGET / _STAGNATION are the spec values.
_MAX_STEPS = 4000
_SPEC_STEP_TARGET = 86_400
_COVERAGE_TARGET = 0.60
_STAGNATION = 500
_SETTLE_BUDGET = 40  # max ticks to wait for quiescence after each arrival
# Small battery so injected EVs complete (and the system spontaneously departs
# them) within the budget — otherwise the station fills and idles.
_EXPLORE_BATTERY_KWH = 5.0
# F1-b demand schedule: every Nth arrival is low-demand (interval shrinks to the
# single anchor while charging → dynamic anchor-relay open). 50 kW ≤ 125−75 so
# the §6.2 return trigger fires (see _smallest_edge_group_power).
_HIGH_DEMAND_KW = 250
_LOW_DEMAND_KW = 50
_LOW_DEMAND_EVERY = 3


async def test_exploration(empty_engine: SimulationEngine, scheduler, tracker: CoverageTracker, capsys) -> None:
    engine = empty_engine
    checks = TickChecks(engine, seed=SEED)

    # Rising-edge quiescence detector + coverage/steady recorder.
    progress = {"was_quiescent": True}

    def on_tick(driver: ExplorationDriver) -> None:
        eng = driver.engine
        completed_step = eng.time_controller.step_index - 1
        checks.run(completed_step)  # per-tick army (raises on violation)
        q = is_quiescent(eng)
        if q and not progress["was_quiescent"]:
            occ, _ = read_state_from_snapshot(eng)
            tracker.record(occ, completed_step)
            run_steady_checks(eng, tracker, completed_step, seed=SEED)  # steady army
        progress["was_quiescent"] = q

    driver = ExplorationDriver(engine, on_tick=on_tick)

    def should_terminate() -> bool:
        tc = engine.time_controller
        if tc.step_index >= _MAX_STEPS:
            return True
        if tracker.node_fraction() >= _COVERAGE_TARGET:
            return True
        if tracker.stagnation(tc.step_index) >= _STAGNATION:
            return True
        return False

    # Record the clean empty start as the first visited node.
    tracker.record(0, 0)

    arrival_count = 0
    await driver.start_actors()
    try:
        while not should_terminate():
            occ, _ = read_state_from_snapshot(engine)
            action = scheduler.choose(occ, tracker)
            if action is not None:
                max_kw = (
                    _LOW_DEMAND_KW if arrival_count % _LOW_DEMAND_EVERY == 0
                    else _HIGH_DEMAND_KW
                )
                arrival_count += 1
                inject_arrive(
                    engine, action.output_idx, action.soc_level,
                    max_kw=max_kw, battery_kwh=_EXPLORE_BATTERY_KWH,
                )
                tracker.note_arrival(action.soc_level)
            # Advance until quiescent or the settle budget is spent.
            for _ in range(_SETTLE_BUDGET):
                await driver.tick()
                if is_quiescent(engine) or driver.is_finished():
                    break
            if driver.is_finished():
                break
    finally:
        await driver.stop_actors()

    _print_report(engine, tracker, checks)

    # Sanity: the loop ran and recorded coverage. (All correctness assertions
    # already fired in-place via the two armies.)
    assert tracker.node_count() >= 1
    # F1-b: the inter-group / A1 checks must have been exercised on the
    # dynamic anchor-open case — otherwise they are vacuous (the decision-2 trap).
    assert checks.anchor_open_while_charging_ticks > 0, (
        "no dynamic anchor inter-group open observed while charging — "
        "inter-group / A1 checks would be vacuous; lower demand further")

    # S5: optionally dump the visited (O,L) set for cross-seed union analysis
    # (union_coverage.py). Unset env var → no dump → behaviour identical to S4.
    if dump_path := os.environ.get("EVCS_DUMP_VISITED"):
        tc = engine.time_controller
        # Mirror _print_report's termination reason (single source: the same
        # expression) — recomputed here only because the dump runs after it.
        termination = (
            "max_steps" if tc.step_index >= _MAX_STEPS else
            "coverage>=60%" if tracker.node_fraction() >= _COVERAGE_TARGET else
            "stagnation>=500"
        )
        tracker.dump_to_json(dump_path, metadata={
            "seed": SEED,
            "epsilon": EPSILON,
            "max_steps": _MAX_STEPS,
            "steps_run": tc.step_index,
            "termination": termination,
            "relay_events": len(engine.event_log),
        })


def _print_report(engine: SimulationEngine, tracker: CoverageTracker, checks: TickChecks) -> None:
    tc = engine.time_controller
    cov = tracker.report()
    reason = (
        "max_steps" if tc.step_index >= _MAX_STEPS else
        "coverage>=60%" if tracker.node_fraction() >= _COVERAGE_TARGET else
        "stagnation>=500"
    )
    lines = [
        "",
        "=== STEP S2.X v4 EXPLORATION REPORT (F1) ===",
        "",
        "[Run]",
        f"- steps={tc.step_index} sim_time={tc.current_time:.0f}s seed={SEED} epsilon={EPSILON}",
        f"- termination={reason} (CI budget _MAX_STEPS={_MAX_STEPS}; "
        f"spec target={_SPEC_STEP_TARGET})",
        f"- relay_events={len(engine.event_log)}",
        "",
        "[Steady army]  all PASS (assert-in-place)",
        "- L1 / L2-conservation / station.validate / "
        "A1+A3(relay↔ownership, inter-group+bridge) / L4a(ownership) / L4b",
        "[Per-tick army]  all PASS (assert-in-place)",
        "- L3 I1..I6 + B1(arrival inter-group-before-output) + B2(departure open last)",
        "",
        "[F1-b dynamic-open evidence (N)]",
        f"- anchor inter-group relay opened while charging: "
        f"{checks.anchor_open_while_charging_ticks} ticks across "
        f"{len(checks.anchor_open_states)} occupancy-states",
        "",
        "[Node coverage (observational, /766)]",
        f"- visited={cov['nodes_visited']}/{cov['nodes_total']} "
        f"({cov['node_fraction']*100:.1f}%)",
        f"- L_distribution={cov['L_distribution']}",
        f"- N_distribution={cov['N_distribution']}",
        "",
        "[Vehicle classes (diagnostic, /70)]",
        f"- visited={cov['vehicle_classes_visited']}/{cov['vehicle_classes_total']}",
        "[Edges (diagnostic)]",
        f"- recorded={cov['edges_recorded']} distinct={cov['distinct_edges']}",
        "",
        "[Unvisited top-20 (O,L) — Hamming + behavioural guess]",
    ]
    for u in cov["unvisited_top20"]:
        lines.append(
            f"- O={u['occupancy_bits']} L={u['node'][1]} "
            f"hamming={u['hamming_to_visited']} :: {u['guess']}")
    lines += [
        "",
        "[Reuse vs new]",
        "- reuse: validator.check/_diff_pair / ChargingStation.validate / "
        "snapshots / event_log",
        "- new: is_quiescent / arrival_scheduler / coverage_tracker / "
        "tick_checks(L3 §11 + B1/B2) / relay_invariants(A1/A3) / steady L4b",
        "- import web: NO / change production: NO / "
        "TrafficSimulator inject: NO / export_csv: NO",
        "",
        "[Notes]",
        "- decision 2 withdrawn: inter-group relays re-included in L2 via A1 "
        "(relay↔ownership state-consistency) + B1 (full required set before "
        "output close). L2-C reversibility removed (unsound — departure opens "
        "R_01/R_23). I2 min-guarantee moved to the close transition (it gates "
        "closing, not staying closed).",
        "- I6 mid-charge latch (decision 1) unchanged.",
        "=== END REPORT ===",
        "",
    ]
    print("\n".join(lines))
