"""Per-tick army (L3 invariants + L2 relay-switch order). Spec §5.3.

Runs every tick via the ``ExplorationDriver`` ``on_tick`` hook. Stateful (held
across ticks) because two checks are inherently temporal:

  - **I6 latch** — SPEC §11 "an Output relay, once closed for a charging EV,
    must stay closed until the EV meets its requirement". We latch ``engaged``
    when the relay is observed CLOSED for a connected, not-yet-COMPLETE EV, and
    flag any later transition to OPEN while still charging.
  - **L2 relay order** — detected from relay-state *transitions* between ticks.

> **I6 precondition — empirically corrected (C1 nuance).** C1 proposed the
> precondition ``connected_vehicle is not None AND present_power_kw > 0``. A
> probe showed a real 2-tick arrival transient where ``Output.present_power_kw``
> is already 125 kW (negotiated against the engaged anchor groups) while the
> Output relay is *still OPEN* — the gun is not yet live, no current flows. The
> naive precondition false-fails there on every arrival. The genuine SPEC §11
> invariant is about not *re-opening* a live gun mid-charge, so we latch on
> "relay observed CLOSED while charging" instead of on ``present_power > 0``.
> The arrival close-sequence (relay OPEN→CLOSED) and the departure teardown
> (after COMPLETE) are both legitimately excluded.

The residual station check reuses ``ChargingStation.validate`` via
``reuse_adapters.run_station_validate`` (S2: that is the same per-tick output
surfaced in ``snapshot["violations"]``); boundary consistency (SPEC §9) is read
from the validator's ``boundary_log``, already populated by the engine's own
``_collect_snapshot`` each tick (no double-run).
"""
from __future__ import annotations

from typing import Any

from simulation.hardware.relay import RelayState
from simulation.modules.mcu_control import (
    GROUPS_PER_MCU,
    OUTPUTS_PER_MCU,
    output_min_guarantee_kw,
)
from simulation.modules.vehicle import VehicleState
from tests.algo_validation.helpers.relay_invariants import (
    required_local_intergroup_indices,
)
from tests.algo_validation.helpers.reuse_adapters import (
    read_state_from_snapshot,
    run_station_validate,
)

_EPS = 1e-6
# Anchor → inner inter-group relay index within a board (O0: G0-G1 = idx 0;
# O1: G2-G3 = idx 2). Closing this relay forms the §11 min-guarantee span.
_ANCHOR_INNER_RELAY = {0: 0, 1: 2}


class TickChecks:
    def __init__(self, engine: Any, seed: int = 12345) -> None:
        self.engine = engine
        self.seed = seed
        n_out = len(engine._all_outputs)
        self._engaged = [False] * n_out
        # Previous relay states for transition detection (L2 order).
        self._prev_out_state: dict[tuple[int, int], RelayState] = {}
        self._prev_anchor_inner: dict[tuple[int, int], RelayState] = {}
        # F1-b evidence: count dynamic anchor inter-group opens DURING charging
        # (interval shrunk to the single anchor while the gun stays live) — the
        # case decision 2 was blind to. occ-states where it was seen.
        self.anchor_open_while_charging_ticks = 0
        self.anchor_open_states: set[int] = set()

    # ── public entry ─────────────────────────────────────────────────────

    def run(self, step_index: int) -> None:
        eng = self.engine
        occ, _ = read_state_from_snapshot(eng)

        def fail(tag: str, gidx: int, detail: str, vid: str | None = None) -> str:
            return (
                f"[{tag}] step={step_index} sim_time={eng.time_controller.current_time:.0f}s "
                f"O={occ:0{len(eng._all_outputs)}b} output={gidx} vehicle={vid} "
                f"layer=tick seed={self.seed} :: {detail}"
            )

        total_rated = sum(sum(b.module_powers) for b in eng.station.boards)

        for mcu_idx, board in enumerate(eng.station.boards):
            for local in range(OUTPUTS_PER_MCU):
                gidx = mcu_idx * OUTPUTS_PER_MCU + local
                output = board.outputs[local]
                out_relay = board.output_relays[local]
                state = eng.mcu_controls[mcu_idx]._output_states[local]
                v = output.connected_vehicle
                vid = v.vehicle_id if v is not None else None
                closed = out_relay.state == RelayState.CLOSED
                teardown = (
                    state.pending_intergroup_open != 0
                    or state.pending_output_relay_open != 0
                    or v is None
                    or (v is not None and v.state == VehicleState.COMPLETE)
                )

                # I1 — available power within physical bounds.
                assert output.available_power_kw >= -_EPS, fail(
                    "L3 I1", gidx, f"negative available {output.available_power_kw}", vid)
                assert output.available_power_kw <= total_rated + _EPS, fail(
                    "L3 I1", gidx,
                    f"available {output.available_power_kw} > rated {total_rated}", vid)

                # I2 — engaged (charging) output keeps at least its anchor group.
                # The §11 min-guarantee gates CLOSING, not staying closed: a
                # low-demand EV's interval can legitimately shrink to the single
                # anchor while charging, dropping available below min-guarantee.
                # The actual §11 gate is asserted at the close transition below.
                if closed and not teardown:
                    anchor_local = 0 if local == 0 else GROUPS_PER_MCU - 1
                    anchor_power = board.groups[anchor_local].total_power_kw
                    assert output.available_power_kw + _EPS >= anchor_power, fail(
                        "L3 I2", gidx,
                        f"available {output.available_power_kw} < anchor {anchor_power}", vid)

                # I3 — pending indicators are structurally valid (∈ {0,1,2}).
                for pname in (
                    "pending_intergroup_close", "pending_output_relay_close",
                    "pending_intergroup_open", "pending_output_relay_open",
                ):
                    pv = getattr(state, pname)
                    assert pv in (0, 1, 2), fail(
                        "L3 I3", gidx, f"{pname}={pv} out of range", vid)

                # I4 — closed output relay ⇒ anchor group owned by it (skip teardown).
                if closed and not teardown:
                    anchor_abs = mcu_idx * GROUPS_PER_MCU + (0 if local == 0 else 3)
                    owner = board.module_assignment.get_owner(anchor_abs)
                    assert owner == gidx, fail(
                        "L3 I4", gidx,
                        f"anchor g{anchor_abs} owner={owner} != output {gidx}", vid)

                # I5 — fully departed output carries no power, relay open.
                if v is None and not teardown:
                    assert not closed, fail(
                        "L3 I5", gidx, "no vehicle but relay CLOSED", vid)
                    assert abs(output.present_power_kw) <= _EPS, fail(
                        "L3 I5", gidx,
                        f"no vehicle but present={output.present_power_kw}", vid)

                # I6 — §11 latch: no mid-charge re-open (see module docstring).
                charging = v is not None and v.state != VehicleState.COMPLETE
                if not charging:
                    self._engaged[gidx] = False
                elif closed:
                    self._engaged[gidx] = True
                if self._engaged[gidx]:
                    assert closed, fail(
                        "L3 I6", gidx,
                        "Output relay OPEN while EV still charging (mid-charge open)", vid)

                # L2 relay-switch order (SPEC §11), on an Output-relay transition.
                # Inter-group relays are back in scope (decision 2 withdrawn):
                #   - B1 CLOSE (arrival): EVERY inter-group relay required by the
                #     output's current interval must already be CLOSED before the
                #     gun closes (inter-group-before-Output). At close time the
                #     interval is the min-guarantee span, but we check the full
                #     required set so a pre-close borrow can't slip through.
                #   - B2 OPEN (departure): the gun opens LAST, only once the EV is
                #     COMPLETE/gone — never mid-charge. The departing inter-group
                #     relays open in an earlier phase (`_advance_relay_phases`
                #     :470-481), so they are NOT still-CLOSED here; final relay↔
                #     ownership consistency is confirmed by A1 at the next settle.
                key = (mcu_idx, local)
                prev = self._prev_out_state.get(key, out_relay.state)
                if out_relay.state != prev:
                    if out_relay.state == RelayState.CLOSED:
                        # §11 min-guarantee gate — asserted at the close moment
                        # (not continuously; see I2 above).
                        min_g = output_min_guarantee_kw(board.module_powers, local)
                        assert output.available_power_kw + _EPS >= min_g, fail(
                            "L3 I2-close", gidx,
                            f"Output closed with available {output.available_power_kw} "
                            f"< min_guarantee {min_g}", vid)
                        if state.interval_min is not None:
                            req = required_local_intergroup_indices(
                                state.interval_min, state.interval_max,
                                mcu_idx, eng.mcu_controls[mcu_idx]._wrap)
                            for ridx in sorted(req):
                                assert board.inter_group_relays[ridx].state == RelayState.CLOSED, fail(
                                    "L2 order B1", gidx,
                                    f"Output closed but required inter-group R{ridx} not CLOSED", vid)
                    else:
                        assert v is None or v.state == VehicleState.COMPLETE, fail(
                            "L2 order B2", gidx,
                            "Output opened while EV not COMPLETE (premature gun open)", vid)
                self._prev_out_state[key] = out_relay.state

                # F1-b evidence counter: anchor inter-group relay opened while
                # the gun is live + EV charging (interval shrunk to single
                # anchor). This is a VALID state (A1 confirms it at settle) — we
                # only count it to prove the inter-group checks are exercised on
                # the dynamic-open case decision 2 missed.
                ai = board.inter_group_relays[_ANCHOR_INNER_RELAY[local]]
                ai_prev = self._prev_anchor_inner.get(key, ai.state)
                if (
                    ai_prev == RelayState.CLOSED
                    and ai.state == RelayState.OPEN
                    and closed
                    and v is not None
                    and v.state != VehicleState.COMPLETE
                ):
                    self.anchor_open_while_charging_ticks += 1
                    self.anchor_open_states.add(occ)
                self._prev_anchor_inner[key] = ai.state

        # Residual station validation (reuse — L2 contiguity / single owner).
        violations = run_station_validate(eng.station)
        assert not violations, (
            f"[L2 station] step={step_index} layer=tick seed={self.seed} "
            f":: {violations}")

        # Boundary consistency (SPEC §9): the engine's own _collect_snapshot
        # already ran validator.check this step; flag any inconsistency it found.
        bad = [e for e in eng.validator.boundary_log
               if e.get("time_step") == step_index and e.get("result") == "inconsistent"]
        assert not bad, (
            f"[L4a boundary] step={step_index} layer=tick seed={self.seed} :: {bad}")
