from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from simulation.base import SimulationModule
from simulation.hardware.relay import RelayState

if TYPE_CHECKING:
    from simulation.data.module_assignment import ModuleAssignment
    from simulation.data.relay_matrix import RelayMatrix
    from simulation.hardware.rectifier_board import RectifierBoard
    from simulation.hardware.relay import Relay
    from simulation.log.relay_event_log import RelayEventLog


CONSECUTIVE_THRESHOLD: int = 3


@dataclass
class OutputPowerState:
    """Per-output tracking for borrow/return decision counters."""

    output_local_idx: int
    anchor_group_idx: int  # global group index
    borrow_counter: int = 0
    return_counter: int = 0
    interval_min: int | None = None
    interval_max: int | None = None


class MCUControl(SimulationModule):
    """Business logic core for a single MCU.

    Monitors Present Power vs Available Power per Output and executes
    borrow/return strategies by switching relays and updating ModuleAssignment.
    """

    def __init__(
        self,
        mcu_id: int,
        board: RectifierBoard,
        module_assignment: ModuleAssignment,
        relay_matrix: RelayMatrix,
        event_log: RelayEventLog,
    ):
        self._mcu_id = mcu_id
        self._board = board
        self._ma = module_assignment
        self._rm = relay_matrix
        self._event_log = event_log
        self._step_index: int = 0
        self._group_base: int = mcu_id * 4
        self._output_base: int = mcu_id * 2

        # Build per-output state, discovering current intervals from MA
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

        # Align relay state with discovered intervals
        self._apply_global_relay_state()

    # ── Public interface ─────────────────────────────────────────────

    def step(self, dt: float) -> None:
        self._step_index += 1

        for i, output in enumerate(self._board.outputs):
            state = self._output_states[i]

            if output.connected_vehicle is None:
                state.borrow_counter = 0
                state.return_counter = 0
                continue

            vehicle = output.connected_vehicle
            present = output.present_power_kw
            available = output.available_power_kw

            # ── Borrow evaluation ──
            if (
                present > 0
                and abs(present - available) < 0.01
                and vehicle.max_require_power_kw > available + 0.01
            ):
                state.borrow_counter += 1
            else:
                state.borrow_counter = 0

            if state.borrow_counter >= CONSECUTIVE_THRESHOLD:
                self._try_borrow(state)
                state.borrow_counter = 0

            # ── Return evaluation ──
            edge_power = self._smallest_edge_group_power(state)
            surplus = available - present
            if edge_power is not None and surplus >= edge_power - 0.01:
                state.return_counter += 1
            else:
                state.return_counter = 0

            if state.return_counter >= CONSECUTIVE_THRESHOLD:
                self._try_return(state)
                state.return_counter = 0

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

    def handle_vehicle_arrival(self, output_local_idx: int) -> None:
        """Called when a new vehicle connects. Detect and resolve conflicts."""
        state = self._output_states[output_local_idx]
        output = self._board.outputs[output_local_idx]

        # Minimum 125 kW = anchor + 1 adjacent
        if output_local_idx == 0:
            required_min = self._group_base
            required_max = self._group_base + 1
        else:
            required_min = self._group_base + 2
            required_max = self._group_base + 3

        # Resolve conflicts: force-return any borrowed groups in our required range
        for g in range(required_min, required_max + 1):
            owner = self._ma.get_owner(g)
            if owner is not None and owner != self._output_base + output_local_idx:
                other_local = owner - self._output_base
                self._force_return_group(other_local, g)

        # Set up interval
        state.interval_min = required_min
        state.interval_max = required_max
        state.borrow_counter = 0
        state.return_counter = 0

        # Configure MA and relays
        for g in range(required_min, required_max + 1):
            self._ma.assign(self._output_base + output_local_idx, g)
        self._apply_global_relay_state()
        self._sync_output(output_local_idx)

    def handle_vehicle_departure(self, output_local_idx: int) -> None:
        """Called when a vehicle finishes or disconnects."""
        state = self._output_states[output_local_idx]
        output_idx = self._output_base + output_local_idx

        if state.interval_min is not None:
            for g in range(state.interval_min, state.interval_max + 1):
                self._ma.release(output_idx, g)

        state.interval_min = None
        state.interval_max = None
        state.borrow_counter = 0
        state.return_counter = 0

        self._apply_global_relay_state()
        self._sync_output(output_local_idx)

    # ── Borrow / Return ──────────────────────────────────────────────

    def _try_borrow(self, state: OutputPowerState) -> None:
        target = self._find_expansion_target(state)
        if target is None:
            return

        old_min, old_max = state.interval_min, state.interval_max
        if target < state.interval_min:
            state.interval_min = target
        else:
            state.interval_max = target

        self._reconfigure_relays(
            state.output_local_idx, state.interval_min, state.interval_max
        )
        # Update MA: assign the new group
        output_idx = self._output_base + state.output_local_idx
        self._ma.assign(output_idx, target)
        self._sync_output(state.output_local_idx)

    def _try_return(self, state: OutputPowerState) -> None:
        target = self._find_shrink_target(state)
        if target is None:
            return

        old_min, old_max = state.interval_min, state.interval_max
        if target == state.interval_min:
            state.interval_min = target + 1
        else:
            state.interval_max = target - 1

        self._reconfigure_relays(
            state.output_local_idx, state.interval_min, state.interval_max
        )
        output_idx = self._output_base + state.output_local_idx
        self._ma.release(output_idx, target)
        self._sync_output(state.output_local_idx)

    def _find_expansion_target(self, state: OutputPowerState) -> int | None:
        """Find the next group to borrow. Priority: right > left."""
        right = state.interval_max + 1
        left = state.interval_min - 1
        output_idx = self._output_base + state.output_local_idx

        # Right first
        if self._can_assign(output_idx, right):
            return right
        # Left second
        if self._can_assign(output_idx, left):
            return left
        return None

    def _find_shrink_target(self, state: OutputPowerState) -> int | None:
        """Find the edge group to return. Anchor is returned last.

        Phase 3 (all local):
          - If MIN == anchor -> return MAX
          - Else -> return MIN
        """
        if state.interval_min == state.interval_max:
            return None  # only anchor remains

        if state.interval_min == state.anchor_group_idx:
            return state.interval_max
        else:
            return state.interval_min

    def _force_return_group(self, other_local_idx: int, group_idx: int) -> None:
        """Force another output to release groups until group_idx is free."""
        state = self._output_states[other_local_idx]
        if state.interval_min is None:
            return

        output_idx = self._output_base + other_local_idx

        # Determine which side to shrink based on anchor position
        if state.anchor_group_idx < group_idx:
            # Group is on the right side of anchor -> shrink MAX
            while state.interval_max >= group_idx and state.interval_max > state.anchor_group_idx:
                released = state.interval_max
                state.interval_max -= 1
                self._ma.release(output_idx, released)
        else:
            # Group is on the left side of anchor -> shrink MIN
            while state.interval_min <= group_idx and state.interval_min < state.anchor_group_idx:
                released = state.interval_min
                state.interval_min += 1
                self._ma.release(output_idx, released)

        self._apply_global_relay_state()
        self._sync_output(other_local_idx)

    # ── Relay switching ──────────────────────────────────────────────

    def _reconfigure_relays(
        self, output_local_idx: int, new_min: int, new_max: int
    ) -> None:
        """Reconfigure all relays based on BOTH outputs' current intervals.

        Inter-group relays are shared, so we compute the global needed set
        from all active outputs to avoid opening relays another output needs.
        """
        # Temporarily update the state for the target output
        # (caller has already updated interval_min/max)
        self._apply_global_relay_state()

    def _apply_global_relay_state(self) -> None:
        """Set all relays to match the union of both outputs' requirements."""
        needed: set[Relay] = set()
        for state in self._output_states:
            if state.interval_min is not None:
                needed.update(self._compute_required_relays(
                    state.output_local_idx, state.interval_min, state.interval_max
                ))

        all_relays = self._board.output_relays + self._board.inter_group_relays

        # Phase 1: open relays not needed by any output
        for r in all_relays:
            if r.state == RelayState.CLOSED and r not in needed:
                r.switch(self._step_index)

        # Phase 2: close relays needed
        for r in needed:
            if r.state == RelayState.OPEN:
                r.switch(self._step_index)

    def _compute_required_relays(
        self, output_local_idx: int, new_min: int, new_max: int
    ) -> list[Relay]:
        """Relays that must be CLOSED for the given interval."""
        min_local = self._global_to_local(new_min)
        max_local = self._global_to_local(new_max)
        relays: list[Relay] = []

        # Output relay is always needed
        relays.append(self._board.output_relays[output_local_idx])

        # Inter-group relays for contiguous chain
        for i in range(min_local, max_local):
            relays.append(self._board.inter_group_relays[i])

        return relays

    # ── Output sync ──────────────────────────────────────────────────

    def _sync_output(self, output_local_idx: int) -> None:
        """Sync Output object's groups list and available_power from interval."""
        state = self._output_states[output_local_idx]
        output = self._board.outputs[output_local_idx]

        if state.interval_min is None or state.interval_max is None:
            output.groups = [output.anchor_group]
            output.available_power_kw = 0.0
            output._group_indices = []
            return

        min_local = self._global_to_local(state.interval_min)
        max_local = self._global_to_local(state.interval_max)
        output.groups = [
            self._board.groups[i] for i in range(min_local, max_local + 1)
        ]
        output.available_power_kw = sum(g.total_power_kw for g in output.groups)
        output._group_indices = list(
            range(state.interval_min, state.interval_max + 1)
        )

    # ── Helpers ───────────────────────────────────────────────────────

    def _global_to_local(self, global_idx: int) -> int:
        return global_idx - self._group_base

    def _local_to_global(self, local_idx: int) -> int:
        return local_idx + self._group_base

    def _is_local_group(self, global_idx: int) -> bool:
        local = global_idx - self._group_base
        return 0 <= local < 4

    def _can_assign(self, output_idx: int, global_group_idx: int) -> bool:
        """Check if a group can be assigned: local, idle, and reachable."""
        if not self._is_local_group(global_group_idx):
            return False
        if self._ma.get_owner(global_group_idx) is not None:
            return False
        if self._ma._matrix[output_idx][global_group_idx] == -1:
            return False
        return True

    def _smallest_edge_group_power(self, state: OutputPowerState) -> float | None:
        """Power of the outermost releasable group (for return threshold)."""
        target = self._find_shrink_target(state)
        if target is None:
            return None
        local = self._global_to_local(target)
        return self._board.groups[local].total_power_kw
