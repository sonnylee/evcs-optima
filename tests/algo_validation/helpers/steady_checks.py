"""Steady-state army — runs when the system is quiescent. Spec §5.2.

  - **L1** state: tracker's L invariant (O=0 ⇔ L=⊥, §2.1).
  - **L2** conservation: no over-delivery (present ≤ available ≤ rated), total
    within station capacity, and global single-ownership (lent ≡ borrowed).
  - **L2** contiguity / single-owner: reuse ``ChargingStation.validate``.
  - **A1/A3** relay ↔ ownership state-consistency for every inter-group + bridge
    relay (``relay_invariants.relay_ownership_violations``) — the F1 re-inclusion
    of inter-group relays into L2 after decision 2 was withdrawn. Subsumes the
    old self-built "CLOSED bridge ⇒ co-owned" check (now both directions, plus
    every inter-group relay, plus the A3 pristine-init exception).
  - **L4a** ownership mirror: reuse ``Validator._diff_pair`` on adjacent pairs.
  - **L4b** borrow closed-loop: every cross-MCU borrowed group is mirrored in
    the lender board's ModuleAssignment (SPEC §10).

L2-C "reversibility to clean init" was REMOVED in F1: F0 proved it unsound — a
departure opens R_01/R_23 (`_open_departure_intergroup_relays:641-643`), so the
station does NOT return to the construction relay vector after activity; the
genuine return-to-empty semantics are covered by A1 (all relays OPEN ⟺ nothing
co-owned) at O=0.
"""
from __future__ import annotations

from typing import Any

from simulation.modules.mcu_control import GROUPS_PER_MCU, OUTPUTS_PER_MCU
from simulation.modules.vehicle import VehicleState
from simulation.utils.topology import adjacent_pairs
from tests.algo_validation.helpers.relay_invariants import relay_ownership_violations
from tests.algo_validation.helpers.reuse_adapters import (
    read_state_from_snapshot,
    run_station_validate,
)

_EPS = 1e-6


def run_steady_checks(
    engine: Any,
    tracker: Any,
    step_index: int,
    seed: int = 12345,
) -> None:
    occ, _ = read_state_from_snapshot(engine)

    def fail(tag: str, detail: str) -> str:
        return (
            f"[{tag}] step={step_index} sim_time={engine.time_controller.current_time:.0f}s "
            f"O={occ:0{len(engine._all_outputs)}b} L={tracker.current_L(occ)} "
            f"layer=steady seed={seed} :: {detail}"
        )

    # ── L1 — tracker L invariant ─────────────────────────────────────────
    L = tracker.current_L(occ)
    if occ == 0:
        assert L is None, fail("L1", f"empty station but L={L!r}")
    else:
        # L may be None only if no arrival was ever noted — impossible once
        # occupied via inject_arrive; assert it is a known bucket.
        assert L in ("low", "mid", "high"), fail("L1", f"occupied but L={L!r}")

    total_rated = sum(sum(b.module_powers) for b in engine.station.boards)

    # ── L2 — conservation (no over-delivery) + single global ownership ───
    # Note: ``Output.available_power_kw`` is a per-output capacity readout that
    # stays at its construction-time anchor sum for idle outputs, so it is NOT
    # globally additive. Real conservation is over *owned groups* — each owned
    # at most once (single ownership), so the delivered total cannot exceed the
    # station's rated capacity.
    global_owner: dict[int, int] = {}
    for mcu_idx, board in enumerate(engine.station.boards):
        for local in range(OUTPUTS_PER_MCU):
            output = board.outputs[local]
            v = output.connected_vehicle
            if v is not None and v.state != VehicleState.COMPLETE:
                assert output.present_power_kw <= output.available_power_kw + _EPS, fail(
                    "L2", f"output {mcu_idx*2+local} present {output.present_power_kw} "
                          f"> available {output.available_power_kw}")
                assert output.present_power_kw <= v.max_require_power_kw + _EPS, fail(
                    "L2", f"output {mcu_idx*2+local} present {output.present_power_kw} "
                          f"> max_require {v.max_require_power_kw}")
        # Single global ownership: collect every group this board owns.
        for local in range(OUTPUTS_PER_MCU):
            abs_o = mcu_idx * OUTPUTS_PER_MCU + local
            for abs_g in board.module_assignment.get_groups_for_output(abs_o):
                prev = global_owner.get(abs_g)
                assert prev is None or prev == abs_o, fail(
                    "L2", f"group {abs_g} claimed by outputs {prev} and {abs_o}")
                global_owner[abs_g] = abs_o

    # Σ power of owned groups ≤ Σ rated (no double-count thanks to single owner).
    owned_power = 0.0
    for abs_g in global_owner:
        phys_mcu = abs_g // GROUPS_PER_MCU
        local_g = abs_g % GROUPS_PER_MCU
        owned_power += engine.station.boards[phys_mcu].groups[local_g].total_power_kw
    assert owned_power <= total_rated + _EPS, fail(
        "L2", f"Σ owned-group power {owned_power} > Σ rated {total_rated}")

    # ── L2 contiguity / single owner (reuse) ─────────────────────────────
    violations = run_station_validate(engine.station)
    assert not violations, fail("L2", f"station.validate: {violations}")

    # ── A1/A3 relay ↔ ownership state-consistency (inter-group + bridge) ──
    # Re-includes every inter-group relay (decision 2 withdrawn). Both
    # directions; covers the dynamic mid-charge anchor-relay open (interval
    # shrunk to a single anchor) and the return-to-empty (all OPEN) case.
    relay_viol = relay_ownership_violations(engine)
    assert not relay_viol, fail("A1", "; ".join(relay_viol))

    # ── L4a ownership mirror (reuse Validator._diff_pair) ────────────────
    N = engine.station.num_mcus
    for left, right in adjacent_pairs(N):
        conflicts = engine.validator._diff_pair(left, right)
        assert not conflicts, fail("L4a", f"MCU pair ({left},{right}) ownership: {conflicts}")

    # ── L4b borrow closed-loop (lender mirrors borrower) ─────────────────
    for abs_g, abs_o in global_owner.items():
        home_mcu = abs_o // OUTPUTS_PER_MCU
        phys_mcu = abs_g // GROUPS_PER_MCU
        if home_mcu == phys_mcu:
            continue  # local, not a cross-MCU borrow
        lender_owner = engine.station.boards[phys_mcu].module_assignment.get_owner(abs_g)
        assert lender_owner == abs_o, fail(
            "L4b", f"borrowed group {abs_g} owned by {abs_o} but lender MCU "
                   f"{phys_mcu} sees {lender_owner}")
