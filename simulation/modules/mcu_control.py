from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from simulation.base import SimulationModule
from simulation.communication.borrow_protocol import send_borrow_request
from simulation.communication.messages import (
    BorrowRequest,
    ConflictRelease,
    ReturnNotify,
    Stop,
    Tick,
)
from simulation.communication.return_protocol import (
    send_conflict_release,
    send_return_notify,
)
from simulation.environment.actor import Actor
from simulation.hardware.relay import RelayState
from simulation.modules.vehicle import VehicleState

# SPEC §11 (docs/SPEC.md L461-467): the minimum power that must be prepared
# before the Output relay may close is per-output and derived from
# ``module_powers``. Default ``[50, 75, 75, 50]`` yields 125 kW for both
# outputs — the legacy hardcoded floor — but non-default configs differ.
def output_min_guarantee_kw(
    module_powers: list[int], output_local_idx: int
) -> float:
    """SPEC §11 per-output minimum guarantee (kW).

    O0 anchors at G0 → guarantee = module_powers[0] + module_powers[1].
    O1 anchors at G3 → guarantee = module_powers[3] + module_powers[2].
    """
    if output_local_idx == 0:
        return float(module_powers[0] + module_powers[1])
    return float(module_powers[3] + module_powers[2])


# SPEC §2.2: each REC BD (one per MCU) holds exactly 4 SMR Groups and 2 Outputs.
# The anchor Groups are the ones physically wired to each Output: G0 for O0,
# G3 for O1. Everything else is derived from these.
GROUPS_PER_MCU = 4
OUTPUTS_PER_MCU = 2
ANCHOR_GROUP_LOCAL_IDX = (0, GROUPS_PER_MCU - 1)

if TYPE_CHECKING:
    from simulation.data.module_assignment import ModuleAssignment
    from simulation.data.relay_matrix import RelayMatrix
    from simulation.hardware.charging_station import ChargingStation
    from simulation.hardware.rectifier_board import RectifierBoard
    from simulation.hardware.relay import Relay
    from simulation.log.relay_event_log import RelayEventLog


# SPEC §6.1/§6.2: trigger must hold for N consecutive steps before borrow/
# return actually fires. Default here matches the historical hard-coded 3;
# runtime value is `MCUControl._consecutive_threshold`, settable via
# `SimulationConfig.consecutive_threshold`.
DEFAULT_CONSECUTIVE_THRESHOLD: int = 3


@dataclass
class OutputPowerState:
    output_local_idx: int
    anchor_group_idx: int  # global group index
    borrow_counter: int = 0
    return_counter: int = 0
    interval_min: int | None = None
    interval_max: int | None = None
    # 0 = no pending action; 1 = armed (skip this tick); 2 = close on next tick.
    # Two-phase arrival: close the output power-switch relay one step after
    # the anchor inter-group relay so the SPEC §11 per-Output minimum-
    # guarantee path is formed first (default config: 125 kW).
    pending_output_relay_close: int = 0
    pending_intergroup_close: int = 0
    # Two-phase departure (SPEC §11): open inter-group relays first, then the
    # output power-switch relay. Mirrors the 1-tick armed / 2-tick execute
    # state machine used for arrival closures.
    pending_intergroup_open: int = 0
    pending_output_relay_open: int = 0
    gun_live_ticks: int = 0

    @property
    def has_interval(self) -> bool:
        return self.interval_min is not None and self.interval_max is not None


class MCUControl(Actor, SimulationModule):
    """Business logic for one MCU. Actor for cross-MCU messaging."""

    def __init__(
        self,
        mcu_id: int,
        board: RectifierBoard,
        module_assignment: ModuleAssignment,
        relay_matrix: RelayMatrix,
        event_log: RelayEventLog,
        station: ChargingStation | None = None,
        num_mcus: int = 1,
        consecutive_threshold: int = DEFAULT_CONSECUTIVE_THRESHOLD,
    ):
        Actor.__init__(self, name=f"MCU{mcu_id}")
        self._mcu_id = mcu_id
        self._board = board
        self._ma = module_assignment
        self._rm = relay_matrix
        self._event_log = event_log
        self._station = station
        self._num_mcus = num_mcus
        self._consecutive_threshold = max(1, consecutive_threshold)
        self._step_index: int = 0
        self._group_base: int = mcu_id * GROUPS_PER_MCU
        self._output_base: int = mcu_id * OUTPUTS_PER_MCU
        self._num_groups_total: int = GROUPS_PER_MCU * num_mcus
        # SPEC §2.2: ring topology kicks in at 3+ MCUs, so inter-MCU
        # borrow/return may wrap across the num_groups_total boundary.
        self._ring_enabled: bool = num_mcus >= 3

        # Neighbor actor refs (wired post-construction by engine)
        self.left_neighbor: MCUControl | None = None
        self.right_neighbor: MCUControl | None = None

        # Departure-time cross-MCU release notifications (SPIKE-XMCU-REPORT
        # Phase A, DP-1/DP-2). `_finalize_departure` runs in the synchronous
        # relay-phase path; it cannot `await send_return_notify`, so it queues
        # (lender_mcu_id, group_phys) pairs here. `_handle_tick` drains them
        # after the per-output loop so the lender resyncs its own MA + relays.
        self._pending_foreign_release_notifies: list[tuple[int, int]] = []

        self._output_states: list[OutputPowerState] = []
        for i in range(OUTPUTS_PER_MCU):
            anchor_global = self._local_to_global(ANCHOR_GROUP_LOCAL_IDX[i])
            state = OutputPowerState(
                output_local_idx=i,
                anchor_group_idx=anchor_global,
            )
            groups = self._ma.get_groups_for_output(self._output_base + i)
            if groups:
                state.interval_min = min(groups)
                state.interval_max = max(groups)
            self._output_states.append(state)

        self._apply_global_relay_state()

    # ── Actor handle ──────────────────────────────────────────────────

    async def handle(self, msg: Any) -> None:
        if isinstance(msg, Tick):
            await self._handle_tick(msg)
        elif isinstance(msg, BorrowRequest):
            await self._handle_borrow_request(msg)
        elif isinstance(msg, ReturnNotify):
            await self._handle_return_notify(msg)
        elif isinstance(msg, ConflictRelease):
            await self._handle_conflict_release(msg)
        elif isinstance(msg, Stop):
            self.stop()

    # ── Synchronous step (Phase 3 back-compat) ───────────────────────

    def step(self, dt: float) -> None:
        """Synchronous local-only step (legacy single-MCU paths)."""
        self._run_local_logic()
        self._step_index += 1

    def _run_local_logic(self) -> None:
        for i, output in enumerate(self._board.outputs):
            state = self._output_states[i]
            if self._pre_step_guard(state, output):
                continue
            # Snapshot pre-borrow available so the return decision uses the
            # same reference value as the original inlined loop (see
            # `_tick_return_condition`).
            pre_available = output.available_power_kw
            if self._tick_borrow_condition(state, output):
                self._try_borrow_local(state)
                state.borrow_counter = 0
            if self._tick_return_condition(state, output, pre_available):
                self._try_return_local(state)
                state.return_counter = 0

    # ── Async tick (Phase 4) ─────────────────────────────────────────

    async def _handle_tick(self, tick: Tick) -> None:
        self._step_index = tick.step_index
        try:
            for i, output in enumerate(self._board.outputs):
                state = self._output_states[i]
                if self._pre_step_guard(state, output):
                    continue
                pre_available = output.available_power_kw
                if self._tick_borrow_condition(state, output):
                    await self._try_borrow_async(state)
                    state.borrow_counter = 0
                if self._tick_return_condition(state, output, pre_available):
                    await self._try_return_async(state)
                    state.return_counter = 0
            # SPEC §11 / DP-2: a departure that ran inside _advance_relay_phases
            # this tick may have queued cross-MCU release notices. Flush them
            # now (in async context) so each lender resyncs its own relays.
            await self._drain_pending_foreign_release_notifies()
        finally:
            tick.done.set()

    # ── Per-step decision helpers (shared by sync + async paths) ──────

    def _pre_step_guard(self, state: OutputPowerState, output: Any) -> bool:
        """True if the borrow/return loop should skip this output (no vehicle
        connected, or a relay-phase transition is in flight)."""
        if output.connected_vehicle is None:
            state.borrow_counter = 0
            state.return_counter = 0
            state.gun_live_ticks = 0
            return True
        return self._advance_relay_phases(state)

    def _tick_borrow_condition(
        self, state: OutputPowerState, output: Any
    ) -> bool:
        """SPEC §6.1 trigger: Present ≈ Available and demand exceeds Available
        for `_consecutive_threshold` ticks. Updates `borrow_counter`; returns
        True iff the threshold was hit this tick."""
        vehicle = output.connected_vehicle
        present = output.present_power_kw
        available = output.available_power_kw
        if (
            present > 0
            and abs(present - available) < 0.01
            and vehicle.max_require_power_kw > available + 0.01
        ):
            state.borrow_counter += 1
        else:
            state.borrow_counter = 0
        return state.borrow_counter >= self._consecutive_threshold

    def _tick_return_condition(
        self, state: OutputPowerState, output: Any, pre_available: float
    ) -> bool:
        """SPEC §6.2 trigger: (Available − demand) ≥ smallest edge Group's power
        for `_consecutive_threshold` ticks. `pre_available` is the pre-borrow
        snapshot, so a same-tick borrow does not immediately enable a return."""
        edge_power = self._smallest_edge_group_power(state)
        demand = output.connected_vehicle.max_require_power_kw
        if edge_power is not None and (pre_available - demand) >= edge_power - 0.01:
            state.return_counter += 1
        else:
            state.return_counter = 0
        return state.return_counter >= self._consecutive_threshold

    # ── Borrow / Return (local only) ─────────────────────────────────

    def _try_borrow_local(self, state: OutputPowerState) -> None:
        target = self._find_expansion_target(state, allow_cross_mcu=False)
        if target is None:
            return
        self._apply_borrow(state, target)

    def _try_return_local(self, state: OutputPowerState) -> None:
        target = self._find_shrink_target(state, prefer_cross_mcu=False)
        if target is None:
            return
        self._apply_return(state, target)

    # ── Borrow / Return (async, cross-MCU aware) ─────────────────────

    async def _try_borrow_async(self, state: OutputPowerState) -> None:
        target = self._find_expansion_target(state, allow_cross_mcu=True)
        if target is None:
            return

        if self._is_local_group(target):
            self._apply_borrow(state, target)
            return

        # Cross-MCU: determine which neighbor owns the target group.
        # `target` may be virtual (wrap across ring edge); dispatch on physical.
        target_phys = self._wrap(target)
        neighbor = self._get_neighbor_for_group(target_phys)

        output_idx = self._output_base + state.output_local_idx
        # SPEC §11: the lender resyncs its own relays inside
        # _handle_borrow_request, which reads our `state.interval_*` to
        # compute required cross-MCU relays. Speculatively extend our
        # interval BEFORE awaiting the request so the lender sees the
        # committed bounds; revert if denied.
        prev_min, prev_max = state.interval_min, state.interval_max
        if target < state.interval_min:
            state.interval_min = target
        elif target > state.interval_max:
            state.interval_max = target

        granted = await send_borrow_request(
            neighbor, self._mcu_id, target_phys, output_idx, self._step_index,
        )
        if not granted:
            state.interval_min, state.interval_max = prev_min, prev_max
            return

        # Lender (neighbor) already reserved `target` in ITS OWN MA AND
        # resynced its own relays inside _handle_borrow_request
        # (SPEC §11). Mirror the same cell into our own 3-MCU window so
        # subsequent _can_assign / get_owner reads on this MCU see the
        # borrowed cell as occupied (SPEC §10), then resync our own relays.
        self._ma.assign_if_idle(output_idx, target_phys)
        self._apply_global_relay_state()
        self._sync_output(state.output_local_idx)

    async def _try_return_async(self, state: OutputPowerState) -> None:
        target = self._find_shrink_target(state, prefer_cross_mcu=True)
        if target is None:
            return

        if not self._is_local_group(target):
            target_phys = self._wrap(target)
            neighbor = self._get_neighbor_for_group(target_phys)
            # SPEC §11: the lender resyncs its own relays inside
            # _handle_return_notify, which reads our `state.interval_*` to
            # decide what cross-MCU relays are still needed. Shrink our
            # interval BEFORE the notify so the lender sees the
            # post-return bounds and opens the now-unneeded relay.
            if target == state.interval_min:
                state.interval_min = target + 1
            else:
                state.interval_max = target - 1
            # Lender clears its own MA AND resyncs its own relays inside
            # _handle_return_notify (SPEC §11 — only the owning MCU may
            # switch its relays).
            await send_return_notify(
                neighbor, self._mcu_id, target_phys, self._step_index,
            )
            # Finalize on our side: refresh local relays + output, release
            # the cell from our MA mirror. (Cannot reuse `_apply_return`:
            # it would shrink the interval a second time.)
            self._apply_global_relay_state()
            output_idx = self._output_base + state.output_local_idx
            self._ma.release(output_idx, target_phys)
            self._mirror_release(output_idx, target_phys)
            self._sync_output(state.output_local_idx)
            return

        self._apply_return(state, target)

    def _apply_borrow(
        self, state: OutputPowerState, target: int,
        already_assigned: bool = False,
    ) -> None:
        """`target` may be virtual (ring wrap); physical index is used for
        ModuleAssignment."""
        if not state.has_interval:
            return
        output_idx = self._output_base + state.output_local_idx
        target_phys = self._wrap(target)
        if not already_assigned:
            if not self._ma.assign_if_idle(output_idx, target_phys):
                # Someone else claimed it between target selection and apply.
                return
            # Mirror to neighbor MAs that share this cell in their window
            # (SPEC §10 — see ChargingStation.assign_across_window).
            self._mirror_assign(output_idx, target_phys)
        if target < state.interval_min:
            state.interval_min = target
        else:
            state.interval_max = target
        self._apply_global_relay_state()
        self._sync_output(state.output_local_idx)

    def _apply_return(self, state: OutputPowerState, target: int) -> None:
        if not state.has_interval:
            return
        if target == state.interval_min:
            state.interval_min = target + 1
        else:
            state.interval_max = target - 1
        self._apply_global_relay_state()
        output_idx = self._output_base + state.output_local_idx
        target_phys = self._wrap(target)
        self._ma.release(output_idx, target_phys)
        self._mirror_release(output_idx, target_phys)
        self._sync_output(state.output_local_idx)

    # ── SPEC §10 mirror sync helpers ─────────────────────────────────

    def _mirror_assign(self, abs_o: int, abs_g: int) -> None:
        """Propagate a local assignment to other boards' MA mirrors."""
        if self._station is not None:
            self._station.assign_across_window(abs_o, abs_g)

    def _mirror_release(self, abs_o: int, abs_g: int) -> None:
        if self._station is not None:
            self._station.release_across_window(abs_o, abs_g)

    # ── Incoming protocol handlers ───────────────────────────────────

    async def _handle_borrow_request(self, msg: BorrowRequest) -> None:
        """Neighbor asks to borrow group `msg.group_idx` in our territory.

        Atomically reserves on grant (closes the cross-actor double-grant race).
        SPEC §11: only the owning MCU switches its relays — resync our own
        inter-group / bridge relays here, stamped at the requester's step_index.
        """
        granted = self._ma.assign_if_idle(
            msg.requester_output_idx, msg.group_idx,
        )
        if granted:
            self._sync_foreign_relays(msg.step_index)
        msg.response.set_result(granted)

    async def _handle_return_notify(self, msg: ReturnNotify) -> None:
        """Neighbor informs us they are releasing a group in our territory.

        SPEC §10: the lender must release the cell from its own MA (the
        borrower's `_apply_return` only updates its mirror). SPEC §11: resync
        our own relays here, stamped at the requester's step_index.
        """
        owner = self._ma.get_owner(msg.group_idx)
        if owner is not None:
            self._ma.release(owner, msg.group_idx)
            self._sync_foreign_relays(msg.step_index)
        msg.response.set_result(True)

    async def _handle_conflict_release(self, msg: ConflictRelease) -> None:
        """Neighbor needs a group we own; forcibly release from the owning output.

        SPEC §10: `_force_return_group` only mutates this MCU's own MA. For a
        released cell physically owned by another MCU, mirror-sync via
        `ReturnNotify` so the lender clears its authoritative entry.
        """
        owner = self._ma.get_owner(msg.group_idx)
        if owner is None:
            msg.response.set_result(True)
            return
        local_out = owner - self._output_base
        if 0 <= local_out < OUTPUTS_PER_MCU:
            released = self._force_return_group(local_out, msg.group_idx)
            for rg in released:
                owner_mcu = rg // GROUPS_PER_MCU
                if owner_mcu != self._mcu_id:
                    neighbor = self._neighbor_by_mcu_id(owner_mcu)
                    if neighbor is not None:
                        await send_return_notify(
                            neighbor, self._mcu_id, rg, self._step_index,
                        )
        msg.response.set_result(self._ma.get_owner(msg.group_idx) is None)

    # ── Vehicle lifecycle ────────────────────────────────────────────

    # ── Relay phase state machine (shared by sync + async paths) ─────

    def _advance_relay_phases(self, state: OutputPowerState) -> bool:
        """Progress arrival-close and departure-open phases.

        Returns True if a phase is still pending (caller should skip
        borrow/return logic this tick).
        """
        i = state.output_local_idx

        # ── Arrival close (SPEC §11: inter-group first, then Output) ──
        if state.pending_intergroup_close == 2:
            self._apply_global_relay_state(include_output=False)
            state.pending_intergroup_close = 0
            state.pending_output_relay_close = 1
        elif state.pending_intergroup_close == 1:
            state.pending_intergroup_close = 2

        if state.pending_output_relay_close == 2:
            # SPEC §11: Output relay may close only after the per-output
            # minimum guarantee is prepared (default config = 125 kW).
            self._sync_output(i)
            min_guarantee = output_min_guarantee_kw(self._board.module_powers, i)
            if self._board.outputs[i].available_power_kw + 1e-9 >= min_guarantee:
                r = self._board.output_relays[i]
                if r.state == RelayState.OPEN:
                    r.switch(self._step_index)
                state.pending_output_relay_close = 0
                self._sync_output(i)
        elif state.pending_output_relay_close == 1:
            state.pending_output_relay_close = 2

        # ── Departure open (SPEC §11: inter-group first, then Output) ──
        if state.pending_intergroup_open == 2:
            self._open_departure_intergroup_relays(state)
            state.pending_intergroup_open = 0
            state.pending_output_relay_open = 1
        elif state.pending_intergroup_open == 1:
            state.pending_intergroup_open = 2

        if state.pending_output_relay_open == 2:
            state.pending_output_relay_open = 0
            self._finalize_departure(state)
            return True
        elif state.pending_output_relay_open == 1:
            state.pending_output_relay_open = 2

        if (
            state.pending_intergroup_close != 0
            or state.pending_output_relay_close != 0
            or state.pending_intergroup_open != 0
            or state.pending_output_relay_open != 0
        ):
            state.borrow_counter = 0
            state.return_counter = 0
            return True
        return False

    def handle_vehicle_arrival(self, output_local_idx: int) -> None:
        state = self._output_states[output_local_idx]
        if output_local_idx == 0:
            required_min = self._group_base
            required_max = self._group_base + 1
        else:
            required_min = self._group_base + 2
            required_max = self._group_base + 3

        # SPEC §6.3 initiator side: anchor groups may already be owned by
        # another Output (same MCU or neighbor via a prior borrow). Force the
        # holder to release before we claim them.
        for g in range(required_min, required_max + 1):
            owner = self._ma.get_owner(g)
            if owner is None or owner == self._output_base + output_local_idx:
                continue
            owner_mcu_id = owner // OUTPUTS_PER_MCU
            other_local = owner - OUTPUTS_PER_MCU * owner_mcu_id
            if owner_mcu_id == self._mcu_id:
                self._force_return_group(other_local, g)
            else:
                neighbor = self._neighbor_by_mcu_id(owner_mcu_id)
                if neighbor is not None:
                    # Pass our step_index so the neighbor's internal
                    # _apply_global_relay_state() (called inside
                    # _force_return_group) stamps relay events at this
                    # tick. SPEC §11: the neighbor switches its own
                    # relays — we don't reach in afterwards.
                    released = neighbor._force_return_group(
                        other_local, g, step_index=self._step_index,
                    )
                    # Mirror-sync our own MA window (SPEC §10): the neighbor
                    # released cells in their own MA, but our 3-MCU window
                    # still shows them as owned.
                    for rg in released:
                        self._ma.release(owner, rg)

        state.interval_min = required_min
        state.interval_max = required_max
        state.borrow_counter = 0
        state.return_counter = 0

        # Defensive sweep: any owner of g that no longer reports g in its
        # interval is stale (e.g. force-return shrank the interval but didn't
        # release this cell because the owner had it via a non-contiguous
        # historical claim). Clear it before we attempt to assign.
        my_idx = self._output_base + output_local_idx
        for g in range(required_min, required_max + 1):
            owner = self._ma.get_owner(g)
            if owner is None or owner == my_idx:
                continue
            owner_state = None
            owner_mcu_id = owner // OUTPUTS_PER_MCU
            owner_local = owner - OUTPUTS_PER_MCU * owner_mcu_id
            if owner_mcu_id == self._mcu_id:
                owner_state = self._output_states[owner_local]
            else:
                nb = self._neighbor_by_mcu_id(owner_mcu_id)
                if nb is not None:
                    owner_state = nb._output_states[owner_local]
            if (
                owner_state is None
                or owner_state.interval_min is None
                or not self._virtual_interval_contains(
                    owner_state.interval_min, owner_state.interval_max, g
                )
            ):
                self._ma.release(owner, g)

        for g in range(required_min, required_max + 1):
            if not self._ma.assign_if_idle(my_idx, g):
                other = self._ma.get_owner(g)
                print(
                    f"  [WARN] step {self._step_index}: arrival at MCU{self._mcu_id}"
                    f" O{output_local_idx} could not claim G{g}; held by Output {other}"
                )
                continue
            self._mirror_assign(my_idx, g)

        # SPEC §11 (relay ownership): no explicit cross-MCU relay sync here.
        # Each neighbor whose territory we touched already resynced its own
        # relays inside `_force_return_group → _apply_global_relay_state`.
        # Three-phase arrival (SPEC §11):
        #   Tick T   — arrival event only (all relays still OFF).
        #   Tick T+1 — close inter-group / bridge relays to form anchor path.
        #   Tick T+2 — close output power-switch relay (gate power to gun).
        state.pending_intergroup_close = 1
        state.gun_live_ticks = 0
        self._sync_output(output_local_idx)

    def initiate_vehicle_departure(self, output_local_idx: int) -> None:
        """Kick off phased departure (SPEC §11): open inter-group relays, then
        the Output relay, then release assignments and disconnect the vehicle.
        Idempotent if already departing."""
        state = self._output_states[output_local_idx]
        if state.pending_intergroup_open != 0 or state.pending_output_relay_open != 0:
            return
        if state.interval_min is None:
            return
        state.borrow_counter = 0
        state.return_counter = 0
        state.pending_intergroup_open = 1

    def _open_departure_intergroup_relays(self, state: OutputPowerState) -> None:
        """Open inter-group / bridge relays needed only by the departing output,
        preserving those still needed by other local or foreign outputs."""
        if not state.has_interval:
            return
        departing = set(self._compute_required_relays(
            state.output_local_idx, state.interval_min, state.interval_max,
            include_output=False,
        ))

        still_needed: set[Relay] = set()
        for s in self._output_states:
            if s is state or s.interval_min is None:
                continue
            still_needed.update(self._compute_required_relays(
                s.output_local_idx, s.interval_min, s.interval_max,
                include_output=False,
            ))

        foreign_seen: set[int] = set()
        for g in range(self._group_base, self._group_base + GROUPS_PER_MCU):
            owner = self._ma.get_owner(g)
            if owner is None:
                continue
            local_out = owner - self._output_base
            if 0 <= local_out < OUTPUTS_PER_MCU:
                continue
            if owner in foreign_seen:
                continue
            foreign_seen.add(owner)
            span = self._foreign_virtual_span(owner)
            if span is None:
                continue
            fmin, fmax = span
            for r in self._compute_required_relays(
                0, fmin, fmax, include_output=False
            ):
                still_needed.add(r)

        # Sort by relay_id so the RelayEventLog (and resulting CSV "Relays Ops"
        # column) is deterministic across runs — set iteration order depends on
        # object hash, which varies between Python processes.
        for r in sorted(departing - still_needed, key=lambda x: x.relay_id):
            if r.state == RelayState.CLOSED:
                r.switch(self._step_index)

    def _finalize_departure(self, state: OutputPowerState) -> None:
        """Open the Output relay, release groups, disconnect the vehicle."""
        output_local_idx = state.output_local_idx
        output_idx = self._output_base + output_local_idx

        # SPEC §11: Output relay must stay CLOSED until the EV has met its
        # charging requirement — never open mid-charge.
        v = self._board.outputs[output_local_idx].connected_vehicle
        if v is not None and v.state != VehicleState.COMPLETE:
            return

        r = self._board.output_relays[output_local_idx]
        if r.state == RelayState.CLOSED:
            r.switch(self._step_index)

        if state.interval_min is not None:
            for g_virt in range(state.interval_min, state.interval_max + 1):
                g_phys = self._wrap(g_virt)
                if self._ma.get_owner(g_phys) != output_idx:
                    continue
                self._ma.release(output_idx, g_phys)
                if self._is_local_group(g_phys):
                    # Local cell: clear neighbour MA mirrors too. Local anchor
                    # groups are mirrored on arrival (handle_vehicle_arrival →
                    # _mirror_assign), so the release must propagate the same
                    # way; this is unchanged from the historical behaviour.
                    self._mirror_release(output_idx, g_phys)
                else:
                    # Foreign (borrowed) cell: `_mirror_release` only clears MA
                    # mirrors — it leaves the LENDER's inter-group / bridge
                    # relays stuck CLOSED (SPIKE-XMCU-REPORT Phase A, DP-1).
                    # Defer a ReturnNotify so the owning MCU clears its own
                    # authoritative MA AND resyncs its relays (SPEC §11: only
                    # the owning MCU switches its relays). Drained in
                    # `_handle_tick` after the per-output loop.
                    owner_mcu_id = g_phys // GROUPS_PER_MCU
                    self._pending_foreign_release_notifies.append(
                        (owner_mcu_id, g_phys)
                    )

        state.interval_min = None
        state.interval_max = None
        state.borrow_counter = 0
        state.return_counter = 0
        state.gun_live_ticks = 0

        self._board.outputs[output_local_idx].disconnect_vehicle()
        self._sync_output(output_local_idx)

    async def _drain_pending_foreign_release_notifies(self) -> None:
        """Flush departure-time cross-MCU release notices (DP-2).

        Each entry tells a lender MCU to release a group we returned on
        departure and resync its own relays (`_handle_return_notify`). Runs in
        the async tick context so it can `await send_return_notify`.
        """
        while self._pending_foreign_release_notifies:
            lender_mcu_id, g_phys = self._pending_foreign_release_notifies.pop(0)
            neighbor = self._neighbor_by_mcu_id(lender_mcu_id)
            if neighbor is None:
                # Defensive: cross-MCU borrow is restricted to immediate
                # neighbours (SPEC §2.2), so the lender is always adjacent.
                # Reaching here means an upstream invariant broke; warn and
                # drop rather than crash production.
                print(
                    f"  [WARN] step {self._step_index}: MCU{self._mcu_id} "
                    f"departure could not notify lender MCU{lender_mcu_id} for "
                    f"G{g_phys} (not an immediate neighbour)"
                )
                continue
            await send_return_notify(
                neighbor, self._mcu_id, g_phys, self._step_index,
            )

    # ── Force return ─────────────────────────────────────────────────

    def _force_return_group(
        self, other_local_idx: int, group_idx: int,
        step_index: int | None = None,
    ) -> list[int]:
        """Release `group_idx` (physical) plus everything beyond it on the same
        edge of the interval. Wrap-aware: the shrink side is chosen by the
        target's virtual position relative to the anchor.

        Returns the released physical group indices, for the caller to
        mirror-sync its MA (SPEC §10) on cross-MCU calls. `step_index`, when
        supplied, is adopted before `_apply_global_relay_state()` so relay
        events are stamped at the requester's tick.
        """
        if step_index is not None:
            self._step_index = step_index
        state = self._output_states[other_local_idx]
        released: list[int] = []
        if not state.has_interval:
            return released
        output_idx = self._output_base + other_local_idx

        # Find the virtual position of the target and the anchor inside the
        # interval by scanning virtual indices once.
        v_target: int | None = None
        v_anchor: int | None = None
        for v in range(state.interval_min, state.interval_max + 1):
            phys = self._wrap(v)
            if v_target is None and phys == group_idx:
                v_target = v
            if v_anchor is None and phys == state.anchor_group_idx:
                v_anchor = v
        if v_target is None:
            return released  # not owned in this interval — nothing to force
        if v_anchor is None:
            # Shouldn't happen, but fall back to physical anchor.
            v_anchor = state.anchor_group_idx

        if v_target > v_anchor:
            while (
                state.interval_max is not None
                and state.interval_max >= v_target
                and state.interval_max > v_anchor
            ):
                released_virt = state.interval_max
                state.interval_max -= 1
                released_phys = self._wrap(released_virt)
                if self._ma.get_owner(released_phys) == output_idx:
                    self._ma.release(output_idx, released_phys)
                    self._mirror_release(output_idx, released_phys)
                released.append(released_phys)
        else:
            while (
                state.interval_min is not None
                and state.interval_min <= v_target
                and state.interval_min < v_anchor
            ):
                released_virt = state.interval_min
                state.interval_min += 1
                released_phys = self._wrap(released_virt)
                if self._ma.get_owner(released_phys) == output_idx:
                    self._ma.release(output_idx, released_phys)
                    self._mirror_release(output_idx, released_phys)
                released.append(released_phys)

        self._apply_global_relay_state()
        self._sync_output(other_local_idx)
        return released

    # ── Target selection ─────────────────────────────────────────────

    def _find_expansion_target(
        self, state: OutputPowerState, allow_cross_mcu: bool
    ) -> int | None:
        """SPEC §6.1 local-first, then §2.2 right > left within same locality.

        Returns a VIRTUAL index (may wrap in ring topology); callers wrap to
        physical when indexing into ModuleAssignment.
        """
        if not state.has_interval:
            return None
        output_idx = self._output_base + state.output_local_idx
        right_v = state.interval_max + 1
        left_v = state.interval_min - 1

        # Span guard: never allow the interval to cover the whole ring.
        if right_v - state.interval_min + 1 > self._num_groups_total:
            right_v = None  # type: ignore[assignment]
        if state.interval_max - left_v + 1 > self._num_groups_total:
            left_v = None  # type: ignore[assignment]

        if right_v is not None and self._can_assign(output_idx, right_v, allow_cross_mcu=False):
            return right_v
        if left_v is not None and self._can_assign(output_idx, left_v, allow_cross_mcu=False):
            return left_v
        if allow_cross_mcu:
            if right_v is not None and self._can_assign(output_idx, right_v, allow_cross_mcu=True):
                return right_v
            if left_v is not None and self._can_assign(output_idx, left_v, allow_cross_mcu=True):
                return left_v
        return None

    def _find_shrink_target(
        self, state: OutputPowerState, prefer_cross_mcu: bool
    ) -> int | None:
        """Anchor returned last. Prefer cross-MCU edges when requested."""
        if not state.has_interval:
            return None
        if state.interval_min == state.interval_max:
            return None

        candidates: list[int] = []
        if state.interval_min != state.anchor_group_idx:
            candidates.append(state.interval_min)
        if state.interval_max != state.anchor_group_idx:
            candidates.append(state.interval_max)
        if not candidates:
            return None

        if prefer_cross_mcu:
            cross = [c for c in candidates if not self._is_local_group(c)]
            if cross:
                return cross[0]
        # Default: outer edge opposite the anchor
        if state.interval_min == state.anchor_group_idx:
            return state.interval_max
        return state.interval_min

    def _can_assign(
        self, output_idx: int, global_group_idx: int, allow_cross_mcu: bool
    ) -> bool:
        # Accept virtual indices (out of [0, num_groups_total)) and wrap in ring mode.
        # Bound against the GLOBAL ring group count, not the per-MCU MA window
        # (which is 12 for N>=2 — a 3-MCU window per SPEC §5.1/§10).
        phys = self._wrap(global_group_idx)
        if phys < 0 or phys >= self._num_groups_total:
            return False
        # Locality check uses the virtual index: any out-of-range (wrapped)
        # target is by definition cross-MCU.
        if not allow_cross_mcu and not self._is_local_group(global_group_idx):
            return False
        if not self._ma.is_assignable(output_idx, phys):
            return False
        if self._ma.get_owner(phys) is not None:
            return False
        return True

    # ── Relay state management ───────────────────────────────────────

    def _sync_foreign_relays(self, step_index: int) -> None:
        """Resync my inter-group/bridge relays after a neighbor's borrow/return
        changed ModuleAssignment in my territory (SPEC §6.3)."""
        self._step_index = step_index
        self._apply_global_relay_state(include_output=False)

    def _apply_global_relay_state(self, include_output: bool = True) -> None:
        """Toggle relays owned by this MCU to match union of output requirements."""
        needed: set[Relay] = set()
        for state in self._output_states:
            if state.interval_min is None:
                continue
            # C1.5b: an output mid-departure has had its inter-group / bridge
            # relays opened by `_open_departure_intergroup_relays`, but its
            # interval is not cleared until `_finalize_departure` one phase-tick
            # later. Counting that stale interval here would re-close the relays
            # the departure just opened (the step-1113 teardown race), orphaning
            # them once the MA is cleared. Departure is the ONLY writer of these
            # two flags (initiate_vehicle_departure → _advance_relay_phases), so
            # skipping on them never affects arrival or steady-state resyncs.
            # Regression: test_relay_phase_teardown.py.
            if (
                state.pending_intergroup_open != 0
                or state.pending_output_relay_open != 0
            ):
                continue
            needed.update(self._compute_required_relays(
                state.output_local_idx, state.interval_min, state.interval_max,
                include_output=include_output,
            ))
        # Cross-MCU borrows: include relays owned by this MCU that are needed
        # by foreign outputs whose intervals extend into our territory. Use
        # each foreign output's virtual span so ring-wrapped intervals aren't
        # flattened by min()/max() on the physical group set.
        foreign_seen: set[int] = set()
        for g in range(self._group_base, self._group_base + GROUPS_PER_MCU):
            owner = self._ma.get_owner(g)
            if owner is None:
                continue
            local_out = owner - self._output_base
            if 0 <= local_out < OUTPUTS_PER_MCU:
                continue  # already handled via local interval
            if owner in foreign_seen:
                continue
            foreign_seen.add(owner)
            span = self._foreign_virtual_span(owner)
            if span is None:
                continue
            fmin, fmax = span
            for r in self._compute_required_relays(
                0, fmin, fmax, include_output=False
            ):
                needed.add(r)

        all_relays = list(self._board.output_relays) + list(self._board.inter_group_relays)
        if self._board.left_bridge_relay is not None:
            all_relays.append(self._board.left_bridge_relay)

        # SPEC §11: never open an Output relay as a side-effect of a borrow/
        # return resync. Output relays are only opened by _finalize_departure
        # after the EV has met its charging requirement.
        output_relay_set_all = set(self._board.output_relays)
        for r in all_relays:
            if r.state == RelayState.CLOSED and r not in needed:
                if r in output_relay_set_all and not include_output:
                    continue
                r.switch(self._step_index)
        # Close inter-group / bridge relays first so the SPEC §11 per-Output
        # minimum-guarantee path (default config: 125 kW) is formed before the
        # Output relay closes (SPEC §11, §17).
        # Sort by relay_id so the close order (and resulting CSV "Relays Ops"
        # column) is deterministic — set iteration order depends on object
        # hash, which varies between Python processes.
        output_relay_set = set(self._board.output_relays)
        needed_sorted = sorted(needed, key=lambda x: x.relay_id)
        for r in needed_sorted:
            if r in output_relay_set:
                continue
            if r.state == RelayState.OPEN:
                r.switch(self._step_index)
        for r in needed_sorted:
            if r not in output_relay_set:
                continue
            if r.state == RelayState.OPEN:
                r.switch(self._step_index)

    def _compute_required_relays(
        self, output_local_idx: int, new_min: int, new_max: int,
        include_output: bool = True,
    ) -> list[Relay]:
        """Relays owned by THIS MCU that must be CLOSED for this interval.

        Accepts virtual indices (ring wrap): each consecutive pair (v, v+1)
        with a physical wire in my territory contributes its relay.
        """
        relays: list[Relay] = []
        if include_output:
            relays.append(self._board.output_relays[output_local_idx])

        gb = self._group_base
        N = self._num_groups_total

        for v in range(new_min, new_max):
            p = self._wrap(v)
            pn = self._wrap(v + 1)
            # Local inter-group relay (both ends in my territory, consecutive).
            if gb <= p <= gb + 2 and pn == p + 1:
                relays.append(self._board.inter_group_relays[p - gb])
                continue
            # Left bridge I own (prev MCU's last local G → my first local G).
            if self._board.left_bridge_relay is not None and pn == gb:
                prev_gb3 = (gb - 1 + N) % N if self._ring_enabled else gb - 1
                if p == prev_gb3:
                    relays.append(self._board.left_bridge_relay)
                    continue
            # Right bridge (owned by next MCU; fetched via station).
            # bridge_relay_between(self._mcu_id) returns the bridge wire
            # between self and self+1; after the flip its owner is the
            # right MCU (next_mcu.left_bridge_relay).
            if self._station is not None and p == gb + GROUPS_PER_MCU - 1:
                next_g0 = (gb + GROUPS_PER_MCU) % N if self._ring_enabled else gb + GROUPS_PER_MCU
                if pn == next_g0:
                    br = self._station.bridge_relay_between(self._mcu_id)
                    if br is not None:
                        relays.append(br)

        return relays

    # ── Output sync ──────────────────────────────────────────────────

    def _sync_output(self, output_local_idx: int) -> None:
        state = self._output_states[output_local_idx]
        output = self._board.outputs[output_local_idx]

        if not state.has_interval:
            output.groups = [output.anchor_group]
            output.available_power_kw = 0.0
            output._group_indices = []
            return

        # Build group list by walking from interval_min to interval_max globally.
        # Cross-MCU groups are fetched from the station's boards. Indices may be
        # virtual (ring wrap) — normalize via _wrap for the physical lookup.
        groups = []
        total_power = 0.0
        for g_virtual in range(state.interval_min, state.interval_max + 1):
            g_global = self._wrap(g_virtual)
            mcu = g_global // GROUPS_PER_MCU
            local = g_global % GROUPS_PER_MCU
            if self._station is not None and 0 <= mcu < len(self._station.boards):
                grp = self._station.boards[mcu].groups[local]
            elif mcu == self._mcu_id:
                grp = self._board.groups[local]
            else:
                continue
            groups.append(grp)
            total_power += grp.total_power_kw

        output.groups = groups
        output.available_power_kw = total_power
        output._group_indices = [
            self._wrap(g) for g in range(state.interval_min, state.interval_max + 1)
        ]

    # ── Status / helpers ─────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        return {
            "mcu_id": self._mcu_id,
            "step_index": self._step_index,
            "outputs": [
                {
                    "output_local_idx": s.output_local_idx,
                    "anchor_group_idx": s.anchor_group_idx,
                    "interval": (
                        [s.interval_min, s.interval_max]
                        if s.interval_min is not None
                        else None
                    ),
                    "borrow_counter": s.borrow_counter,
                    "return_counter": s.return_counter,
                }
                for s in self._output_states
            ],
        }

    def _global_to_local(self, global_idx: int) -> int:
        return global_idx - self._group_base

    def _local_to_global(self, local_idx: int) -> int:
        return local_idx + self._group_base

    def _wrap(self, virtual_idx: int) -> int:
        """Map a virtual group index to a physical one.

        Wraps only in ring topology (num_mcus >= 3); linear leaves it untouched
        so out-of-range values fall through callers' bounds checks.
        """
        if self._ring_enabled:
            return virtual_idx % self._num_groups_total
        return virtual_idx

    def _virtual_interval_contains(
        self, vmin: int | None, vmax: int | None, g_phys: int
    ) -> bool:
        """Does the virtual interval [vmin, vmax] cover the given physical group?"""
        if vmin is None or vmax is None:
            return False
        if not self._ring_enabled:
            return vmin <= g_phys <= vmax
        N = self._num_groups_total
        for v in (g_phys, g_phys - N, g_phys + N):
            if vmin <= v <= vmax:
                return True
        return False

    def _foreign_virtual_span(
        self, foreign_output_idx: int
    ) -> tuple[int, int] | None:
        """Read a sibling Output's virtual interval through its MCU.

        Valid only for this MCU or an adjacent one (SPEC §11 restricts
        cross-MCU borrow to neighbors).
        """
        owner_mcu_id = foreign_output_idx // OUTPUTS_PER_MCU
        owner_local = foreign_output_idx - owner_mcu_id * OUTPUTS_PER_MCU
        mcu = None
        if owner_mcu_id == self._mcu_id:
            mcu = self
        else:
            mcu = self._neighbor_by_mcu_id(owner_mcu_id)
        if mcu is None:
            return None
        if not (0 <= owner_local < len(mcu._output_states)):
            return None
        s = mcu._output_states[owner_local]
        if not s.has_interval:
            return None
        # Phase B teardown race (docs/algo_validation/SPIKE_A1_BRIDGE_SEED1.md):
        # a foreign output mid-departure has already had its inter-group / bridge
        # relays opened by `_open_departure_intergroup_relays`, but its interval
        # and MA ownership are not cleared until `_finalize_departure` one
        # phase-tick later. A lender re-syncing inside that window (e.g. driven
        # by its own return) would otherwise count this stale interval and
        # re-CLOSE the boundary bridge the departure just opened, orphaning it
        # once the MA clears (seed-1 step-3094 re-close → step-3099 A1 fire).
        # Skip it — symmetric to the local-interval guard in
        # `_apply_global_relay_state`. Normal borrow-in (no pending open) is
        # unaffected, so the bridge still CLOSEs on a live cross-MCU borrow.
        if s.pending_intergroup_open != 0 or s.pending_output_relay_open != 0:
            return None
        return (s.interval_min, s.interval_max)

    def _neighbor_by_mcu_id(self, mcu_id: int) -> MCUControl | None:
        if self._num_mcus <= 1:
            return None
        if mcu_id == (self._mcu_id + 1) % self._num_mcus:
            return self.right_neighbor
        if mcu_id == (self._mcu_id - 1 + self._num_mcus) % self._num_mcus:
            return self.left_neighbor
        return None

    def _get_neighbor_for_group(self, group_phys: int) -> MCUControl | None:
        """Pick the neighbor MCU owning `group_phys` for borrow/return dispatch.
        Non-adjacent groups fall through to `left_neighbor` (already filtered by
        `_can_assign` reachability; SPEC §2.2 restricts borrow to neighbors)."""
        neighbor_mcu = group_phys // GROUPS_PER_MCU
        if neighbor_mcu == (self._mcu_id + 1) % self._num_mcus:
            return self.right_neighbor
        return self.left_neighbor

    def _is_local_group(self, global_idx: int) -> bool:
        local = global_idx - self._group_base
        return 0 <= local < GROUPS_PER_MCU

    def _smallest_edge_group_power(self, state: OutputPowerState) -> float | None:
        target = self._find_shrink_target(state, prefer_cross_mcu=True)
        if target is None:
            return None
        target_phys = self._wrap(target)
        mcu = target_phys // GROUPS_PER_MCU
        local = target_phys % GROUPS_PER_MCU
        if self._station is not None and 0 <= mcu < len(self._station.boards):
            return self._station.boards[mcu].groups[local].total_power_kw
        if self._is_local_group(target):
            return self._board.groups[local].total_power_kw
        return None
