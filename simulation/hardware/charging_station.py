from typing import Any

from simulation.base import SimulationModule
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.log.relay_event_log import RelayEventLog


class ChargingStation(SimulationModule):
    """Charging station shell — global container, no business logic.

    Per SPEC §10, this shell does NOT own a global ``RelayMatrix`` or
    ``ModuleAssignment``. Each ``RectifierBoard`` owns its own per-MCU
    instance; cross-MCU consistency is enforced by the protocol layer
    and verified by the boundary-consistency check (SPEC §9).
    """

    def __init__(self, mcu_id: int = 0, event_log: RelayEventLog | None = None, num_mcus: int = 1):
        self.mcu_id = mcu_id  # kept for back-compat (legacy single-MCU demos)
        self.num_mcus = num_mcus
        self.event_log = event_log if event_log is not None else RelayEventLog()

        # Determine which MCUs own a right bridge:
        # - ring (num_mcus >= 3): every MCU owns its right bridge (wrap-around)
        # - linear (num_mcus == 2): MCU 0 owns the only bridge
        # - single MCU: no bridges
        def has_right_bridge(i: int) -> bool:
            if num_mcus <= 1:
                return False
            if num_mcus >= 3:
                return True
            return i < num_mcus - 1

        self.boards: list[RectifierBoard] = [
            RectifierBoard(
                mcu_id=i,
                event_log=self.event_log,
                num_mcus=num_mcus,
                has_right_bridge=has_right_bridge(i),
            )
            for i in range(num_mcus)
        ]

    @property
    def rectifier_board(self) -> RectifierBoard:
        """Back-compat alias for single-MCU callers."""
        return self.boards[0]

    def initialize(self, dt_index: int = 0) -> None:
        for b in self.boards:
            b.initialize_relays(dt_index)

    def bridge_relay_between(self, left_mcu: int):
        """Return the bridge relay owned by `left_mcu` (i.e., left_mcu ↔ left_mcu+1)."""
        if 0 <= left_mcu < len(self.boards):
            return self.boards[left_mcu].right_bridge_relay
        return None

    # ── Per-MCU MA mirror sync (SPEC §10) ─────────────────────────────
    #
    # In real hardware, a MCU broadcasts ownership changes to neighbors
    # via the CAN bus (SPEC §7.2). The simulation models this with a
    # station-level fan-out: write the (Output, Group) cell to every
    # board's MA whose 3-MCU window covers it. Boards outside the
    # window silently no-op via abs-API translation.

    def assign_across_window(self, abs_output_idx: int, abs_group_idx: int) -> None:
        for board in self.boards:
            board.module_assignment.assign_if_idle(abs_output_idx, abs_group_idx)

    def release_across_window(self, abs_output_idx: int, abs_group_idx: int) -> None:
        for board in self.boards:
            board.module_assignment.release(abs_output_idx, abs_group_idx)

    def validate(self) -> list[str]:
        """Aggregate per-MCU contiguity / single-owner violations.

        Each board's ModuleAssignment now covers a 3-MCU window, so we
        only inspect each board's *own* outputs (avoids double-counting
        through neighbor mirrors). Multi-owner detection runs per group;
        the canonical answer lives on the group's owning MCU board.
        """
        violations: list[str] = []
        ring = self.num_mcus >= 3
        for board in self.boards:
            ma = board.module_assignment
            o_base = board.mcu_id * 2
            for o_local in range(2):
                abs_o = o_base + o_local
                groups = ma.get_groups_for_output(abs_o)
                if groups and not ma.is_contiguous(abs_o, ring=ring):
                    violations.append(f"Output {abs_o}: non-contiguous groups {groups}")
            g_base = board.mcu_id * 4
            for g_off in range(4):
                abs_g = g_base + g_off
                # Multi-owner check uses the OWNING board's MA — that's the
                # canonical view of own-territory ownership.
                local_g = ma.abs_to_local_group(abs_g)
                if local_g is None:
                    continue
                owners_local = [
                    o for o in range(ma.num_outputs)
                    if ma._matrix[o][local_g] == 1
                ]
                if len(owners_local) > 1:
                    abs_owners = [ma.local_to_abs_output(o) for o in owners_local]
                    violations.append(f"Group {abs_g}: multiple owners {abs_owners}")
        return violations

    def step(self, dt: float) -> None:
        for b in self.boards:
            b.step(dt)

    def get_status(self) -> dict[str, Any]:
        return {
            "num_mcus": self.num_mcus,
            "boards": [b.get_status() for b in self.boards],
            "boards_data": [
                {
                    "mcu_id": b.mcu_id,
                    "relay_matrix": b.relay_matrix.to_dict(),
                    "module_assignment": b.module_assignment.to_dict(),
                }
                for b in self.boards
            ],
        }
