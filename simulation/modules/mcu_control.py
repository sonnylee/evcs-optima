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

if TYPE_CHECKING:
    from simulation.data.module_assignment import ModuleAssignment
    from simulation.data.relay_matrix import RelayMatrix
    from simulation.hardware.charging_station import ChargingStation
    from simulation.hardware.rectifier_board import RectifierBoard
    from simulation.hardware.relay import Relay
    from simulation.log.relay_event_log import RelayEventLog


CONSECUTIVE_THRESHOLD: int = 3


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
    # the anchor inter-group relay so the 125 kW path is formed first.
    pending_output_relay_close: int = 0
    pending_intergroup_close: int = 0
    # Two-phase departure (SPEC §11): open inter-group relays first, then the
    # output power-switch relay. Mirrors the 1-tick armed / 2-tick execute
    # state machine used for arrival closures.
    pending_intergroup_open: int = 0
    pending_output_relay_open: int = 0
    gun_live_ticks: int = 0


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
    ):
        Actor.__init__(self, name=f"MCU{mcu_id}")
        self._mcu_id = mcu_id
        self._board = board
        self._ma = module_assignment
        self._rm = relay_matrix
        self._event_log = event_log
        self._station = station
        self._num_mcus = num_mcus
        self._step_index: int = 0
        self._group_base: int = mcu_id * 4
        self._output_base: int = mcu_id * 2

        # Neighbor actor refs (wired post-construction by engine)
        self.left_neighbor: MCUControl | None = None
        self.right_neighbor: MCUControl | None = None

        self._output_states: list[OutputPowerState] = []
        anchor_locals = [0, 3]
        for i in range(2):
            anchor_global = self._local_to_global(anchor_locals[i])
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
        """Synchronous local-only step (used by legacy single-MCU paths)."""
        self._step_index += 1
        self._run_local_logic()

    def _run_local_logic(self) -> None:
        for i, output in enumerate(self._board.outputs):
            state = self._output_states[i]
            if output.connected_vehicle is None:
                state.borrow_counter = 0
                state.return_counter = 0
                state.gun_live_ticks = 0
                continue

            if self._advance_relay_phases(state):
                continue

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

            if state.borrow_counter >= CONSECUTIVE_THRESHOLD:
                self._try_borrow_local(state)
                state.borrow_counter = 0

            edge_power = self._smallest_edge_group_power(state)
            demand = vehicle.max_require_power_kw
            if edge_power is not None and (available - demand) >= edge_power - 0.01:
                state.return_counter += 1
            else:
                state.return_counter = 0

            if state.return_counter >= CONSECUTIVE_THRESHOLD:
                self._try_return_local(state)
                state.return_counter = 0

    # ── Async tick (Phase 4) ─────────────────────────────────────────

    async def _handle_tick(self, tick: Tick) -> None:
        self._step_index = tick.step_index
        try:
            for i, output in enumerate(self._board.outputs):
                state = self._output_states[i]
                if output.connected_vehicle is None:
                    state.borrow_counter = 0
                    state.return_counter = 0
                    state.gun_live_ticks = 0
                    continue

                if self._advance_relay_phases(state):
                    continue

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

                if state.borrow_counter >= CONSECUTIVE_THRESHOLD:
                    await self._try_borrow_async(state)
                    state.borrow_counter = 0

                edge_power = self._smallest_edge_group_power(state)
                demand = vehicle.max_require_power_kw
                if edge_power is not None and (available - demand) >= edge_power - 0.01:
                    state.return_counter += 1
                else:
                    state.return_counter = 0

                if state.return_counter >= CONSECUTIVE_THRESHOLD:
                    await self._try_return_async(state)
                    state.return_counter = 0
        finally:
            tick.done.set()

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

        # Cross-MCU: determine which neighbor owns the target group
        neighbor_mcu = target // 4
        if neighbor_mcu == (self._mcu_id + 1) % self._num_mcus:
            neighbor = self.right_neighbor
        else:
            neighbor = self.left_neighbor

        granted = await send_borrow_request(neighbor, self._mcu_id, target)
        if granted:
            self._apply_borrow(state, target)
            if neighbor is not None:
                neighbor._sync_foreign_relays(self._step_index)

    async def _try_return_async(self, state: OutputPowerState) -> None:
        target = self._find_shrink_target(state, prefer_cross_mcu=True)
        if target is None:
            return

        if not self._is_local_group(target):
            neighbor_mcu = target // 4
            if neighbor_mcu == (self._mcu_id + 1) % self._num_mcus:
                neighbor = self.right_neighbor
            else:
                neighbor = self.left_neighbor
            await send_return_notify(neighbor, self._mcu_id, target)

        self._apply_return(state, target)
        if not self._is_local_group(target) and neighbor is not None:
            neighbor._sync_foreign_relays(self._step_index)

    def _apply_borrow(self, state: OutputPowerState, target: int) -> None:
        if state.interval_min is None or state.interval_max is None:
            return
        if target < state.interval_min:
            state.interval_min = target
        else:
            state.interval_max = target
        self._apply_global_relay_state()
        output_idx = self._output_base + state.output_local_idx
        self._ma.assign(output_idx, target)
        self._sync_output(state.output_local_idx)

    def _apply_return(self, state: OutputPowerState, target: int) -> None:
        if state.interval_min is None or state.interval_max is None:
            return
        if target == state.interval_min:
            state.interval_min = target + 1
        else:
            state.interval_max = target - 1
        self._apply_global_relay_state()
        output_idx = self._output_base + state.output_local_idx
        self._ma.release(output_idx, target)
        self._sync_output(state.output_local_idx)

    # ── Incoming protocol handlers ───────────────────────────────────

    async def _handle_borrow_request(self, msg: BorrowRequest) -> None:
        """Neighbor asks to borrow group `msg.group_idx` (in our territory)."""
        # Grant iff idle, reachable by requester, and not breaking our minimum
        owner = self._ma.get_owner(msg.group_idx)
        granted = False
        if owner is None:
            # Also ensure we ourselves don't currently need this group
            # (only our outputs could need it; they would already own it)
            granted = True
        msg.response.set_result(granted)

    async def _handle_return_notify(self, msg: ReturnNotify) -> None:
        """Neighbor informs us they are releasing a group in our territory."""
        msg.response.set_result(True)

    async def _handle_conflict_release(self, msg: ConflictRelease) -> None:
        """Neighbor needs a group we own; forcibly release from the owning output."""
        owner = self._ma.get_owner(msg.group_idx)
        if owner is None:
            msg.response.set_result(True)
            return
        local_out = owner - self._output_base
        if 0 <= local_out < 2:
            self._force_return_group(local_out, msg.group_idx)
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

        for g in range(required_min, required_max + 1):
            owner = self._ma.get_owner(g)
            if owner is not None and owner != self._output_base + output_local_idx:
                other_local = owner - self._output_base
                if 0 <= other_local < 2:
                    self._force_return_group(other_local, g)

        state.interval_min = required_min
        state.interval_max = required_max
        state.borrow_counter = 0
        state.return_counter = 0

        for g in range(required_min, required_max + 1):
            if self._ma.get_owner(g) is None:
                self._ma.assign(self._output_base + output_local_idx, g)
        # Three-phase arrival (SPEC §11):
        #   Tick T   — arrival event only (all relays still OFF).
        #   Tick T+1 — close inter-group / bridge relays to form anchor path.
        #   Tick T+2 — close output power-switch relay (gate power to gun).
        state.pending_intergroup_close = 1
        state.gun_live_ticks = 0
        self._sync_output(output_local_idx)

    def initiate_vehicle_departure(self, output_local_idx: int) -> None:
        """Kick off phased departure (SPEC §11): open inter-group relays next
        tick, open Output relay the tick after, then release assignments and
        disconnect the vehicle. Idempotent if already departing."""
        state = self._output_states[output_local_idx]
        if state.pending_intergroup_open != 0 or state.pending_output_relay_open != 0:
            return
        if state.interval_min is None:
            return
        state.borrow_counter = 0
        state.return_counter = 0
        state.pending_intergroup_open = 1

    def _open_departure_intergroup_relays(self, state: OutputPowerState) -> None:
        """Open inter-group / bridge relays uniquely needed by the departing
        output's interval. Preserve relays still needed by the other local
        output (or by foreign outputs borrowing our territory)."""
        if state.interval_min is None or state.interval_max is None:
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

        for g in range(self._group_base, self._group_base + 4):
            owner = self._ma.get_owner(g)
            if owner is None:
                continue
            local_out = owner - self._output_base
            if 0 <= local_out < 2:
                continue
            groups = self._ma.get_groups_for_output(owner)
            if not groups:
                continue
            gmin, gmax = min(groups), max(groups)
            local_lo = max(gmin, self._group_base)
            local_hi = min(gmax, self._group_base + 3)
            for gg in range(local_lo, local_hi):
                li = gg - self._group_base
                if 0 <= li < 3:
                    still_needed.add(self._board.inter_group_relays[li])
            if (
                self._board.right_bridge_relay is not None
                and gmin <= self._group_base + 3
                and gmax >= self._group_base + 4
            ):
                still_needed.add(self._board.right_bridge_relay)

        for r in departing - still_needed:
            if r.state == RelayState.CLOSED:
                r.switch(self._step_index)

    def _finalize_departure(self, state: OutputPowerState) -> None:
        """Open the Output relay, release groups, disconnect the vehicle."""
        output_local_idx = state.output_local_idx
        output_idx = self._output_base + output_local_idx

        r = self._board.output_relays[output_local_idx]
        if r.state == RelayState.CLOSED:
            r.switch(self._step_index)

        if state.interval_min is not None:
            for g in range(state.interval_min, state.interval_max + 1):
                if self._ma.get_owner(g) == output_idx:
                    self._ma.release(output_idx, g)

        state.interval_min = None
        state.interval_max = None
        state.borrow_counter = 0
        state.return_counter = 0
        state.gun_live_ticks = 0

        self._board.outputs[output_local_idx].disconnect_vehicle()
        self._sync_output(output_local_idx)

    # ── Force return ─────────────────────────────────────────────────

    def _force_return_group(self, other_local_idx: int, group_idx: int) -> None:
        state = self._output_states[other_local_idx]
        if state.interval_min is None:
            return
        output_idx = self._output_base + other_local_idx

        if state.anchor_group_idx < group_idx:
            while (
                state.interval_max is not None
                and state.interval_max >= group_idx
                and state.interval_max > state.anchor_group_idx
            ):
                released = state.interval_max
                state.interval_max -= 1
                if self._ma.get_owner(released) == output_idx:
                    self._ma.release(output_idx, released)
        else:
            while (
                state.interval_min is not None
                and state.interval_min <= group_idx
                and state.interval_min < state.anchor_group_idx
            ):
                released = state.interval_min
                state.interval_min += 1
                if self._ma.get_owner(released) == output_idx:
                    self._ma.release(output_idx, released)

        self._apply_global_relay_state()
        self._sync_output(other_local_idx)

    # ── Target selection ─────────────────────────────────────────────

    def _find_expansion_target(
        self, state: OutputPowerState, allow_cross_mcu: bool
    ) -> int | None:
        """Priority: right > left."""
        if state.interval_min is None or state.interval_max is None:
            return None
        output_idx = self._output_base + state.output_local_idx
        right = state.interval_max + 1
        left = state.interval_min - 1

        if self._can_assign(output_idx, right, allow_cross_mcu):
            return right
        if self._can_assign(output_idx, left, allow_cross_mcu):
            return left
        return None

    def _find_shrink_target(
        self, state: OutputPowerState, prefer_cross_mcu: bool
    ) -> int | None:
        """Anchor returned last. Prefer cross-MCU edges when requested."""
        if state.interval_min is None or state.interval_max is None:
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
        if global_group_idx < 0 or global_group_idx >= self._ma.num_groups:
            return False
        if not allow_cross_mcu and not self._is_local_group(global_group_idx):
            return False
        if self._ma._matrix[output_idx][global_group_idx] == -1:
            return False
        if self._ma.get_owner(global_group_idx) is not None:
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
            if state.interval_min is not None:
                needed.update(self._compute_required_relays(
                    state.output_local_idx, state.interval_min, state.interval_max,
                    include_output=include_output,
                ))
        # Cross-MCU borrows: include relays owned by this MCU that are needed
        # by foreign outputs whose intervals extend into our territory.
        for g in range(self._group_base, self._group_base + 4):
            owner = self._ma.get_owner(g)
            if owner is None:
                continue
            local_out = owner - self._output_base
            if 0 <= local_out < 2:
                continue  # already handled via local interval
            groups = self._ma.get_groups_for_output(owner)
            if not groups:
                continue
            gmin, gmax = min(groups), max(groups)
            local_lo = max(gmin, self._group_base)
            local_hi = min(gmax, self._group_base + 3)
            for gg in range(local_lo, local_hi):
                li = gg - self._group_base
                if 0 <= li < 3:
                    needed.add(self._board.inter_group_relays[li])
            if (
                self._board.right_bridge_relay is not None
                and gmin <= self._group_base + 3
                and gmax >= self._group_base + 4
            ):
                needed.add(self._board.right_bridge_relay)

        all_relays = list(self._board.output_relays) + list(self._board.inter_group_relays)
        if self._board.right_bridge_relay is not None:
            all_relays.append(self._board.right_bridge_relay)

        for r in all_relays:
            if r.state == RelayState.CLOSED and r not in needed:
                r.switch(self._step_index)
        # Close inter-group / bridge relays first so the 125 kW path is
        # formed before the Output relay closes (SPEC §11, §17).
        output_relay_set = set(self._board.output_relays)
        for r in needed:
            if r in output_relay_set:
                continue
            if r.state == RelayState.OPEN:
                r.switch(self._step_index)
        for r in needed:
            if r not in output_relay_set:
                continue
            if r.state == RelayState.OPEN:
                r.switch(self._step_index)

    def _compute_required_relays(
        self, output_local_idx: int, new_min: int, new_max: int,
        include_output: bool = True,
    ) -> list[Relay]:
        """Relays owned by THIS MCU that must be CLOSED for this interval."""
        relays: list[Relay] = []
        if include_output:
            relays.append(self._board.output_relays[output_local_idx])

        # Local inter-group relays (within this MCU's 4 groups)
        local_lo = max(new_min, self._group_base)
        local_hi = min(new_max, self._group_base + 3)
        for g in range(local_lo, local_hi):
            local_i = g - self._group_base
            if 0 <= local_i < 3:
                relays.append(self._board.inter_group_relays[local_i])

        # Right bridge: needed iff interval spans from this MCU into next
        if (
            self._board.right_bridge_relay is not None
            and new_min <= self._group_base + 3
            and new_max >= self._group_base + 4
        ):
            relays.append(self._board.right_bridge_relay)

        # Left bridge (owned by prev MCU): needed iff interval extends left into prev MCU
        if (
            self._station is not None
            and new_min < self._group_base
            and new_max >= self._group_base
        ):
            prev_mcu = (self._mcu_id - 1 + self._num_mcus) % self._num_mcus
            br = self._station.bridge_relay_between(prev_mcu)
            if br is not None:
                relays.append(br)

        return relays

    # ── Output sync ──────────────────────────────────────────────────

    def _sync_output(self, output_local_idx: int) -> None:
        state = self._output_states[output_local_idx]
        output = self._board.outputs[output_local_idx]

        if state.interval_min is None or state.interval_max is None:
            output.groups = [output.anchor_group]
            output.available_power_kw = 0.0
            output._group_indices = []
            return

        # Build group list by walking from interval_min to interval_max globally.
        # Cross-MCU groups are fetched from the station's boards.
        groups = []
        total_power = 0.0
        for g_global in range(state.interval_min, state.interval_max + 1):
            mcu = g_global // 4
            local = g_global % 4
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
        output._group_indices = list(range(state.interval_min, state.interval_max + 1))

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

    def _is_local_group(self, global_idx: int) -> bool:
        local = global_idx - self._group_base
        return 0 <= local < 4

    def _smallest_edge_group_power(self, state: OutputPowerState) -> float | None:
        target = self._find_shrink_target(state, prefer_cross_mcu=False)
        if target is None:
            return None
        mcu = target // 4
        local = target % 4
        if self._station is not None and 0 <= mcu < len(self._station.boards):
            return self._station.boards[mcu].groups[local].total_power_kw
        if self._is_local_group(target):
            return self._board.groups[local].total_power_kw
        return None
