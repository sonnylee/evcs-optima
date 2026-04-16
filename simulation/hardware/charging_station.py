from typing import Any

from simulation.base import SimulationModule
from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.log.relay_event_log import RelayEventLog


class ChargingStation(SimulationModule):
    """Charging station shell — global container, no business logic."""

    def __init__(self, mcu_id: int = 0, event_log: RelayEventLog | None = None, num_mcus: int = 1):
        self.mcu_id = mcu_id  # kept for back-compat (legacy single-MCU demos)
        self.num_mcus = num_mcus
        self.event_log = event_log if event_log is not None else RelayEventLog()
        self.relay_matrix = RelayMatrix(num_mcus)
        self.module_assignment = ModuleAssignment(
            num_outputs=2 * num_mcus,
            num_groups=4 * num_mcus,
            num_mcus=num_mcus,
        )

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
                relay_matrix=self.relay_matrix,
                module_assignment=self.module_assignment,
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

    def validate(self) -> list[str]:
        violations: list[str] = []
        ma = self.module_assignment
        ring = self.num_mcus >= 3
        for o in range(ma.num_outputs):
            groups = ma.get_groups_for_output(o)
            if groups and not ma.is_contiguous(o, ring=ring):
                violations.append(f"Output {o}: non-contiguous groups {groups}")
        for g in range(ma.num_groups):
            owners = [o for o in range(ma.num_outputs) if ma._matrix[o][g] == 1]
            if len(owners) > 1:
                violations.append(f"Group {g}: multiple owners {owners}")
        return violations

    def step(self, dt: float) -> None:
        for b in self.boards:
            b.step(dt)

    def get_status(self) -> dict[str, Any]:
        return {
            "num_mcus": self.num_mcus,
            "boards": [b.get_status() for b in self.boards],
            "relay_matrix": self.relay_matrix.to_dict(),
            "module_assignment": self.module_assignment.to_dict(),
        }
