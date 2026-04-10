from typing import Any

from simulation.base import SimulationModule
from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.log.relay_event_log import RelayEventLog


class ChargingStation(SimulationModule):
    """Charging station shell — global container, no business logic."""

    def __init__(self, mcu_id: int, event_log: RelayEventLog, num_mcus: int = 1):
        self.mcu_id = mcu_id
        self.num_mcus = num_mcus
        self.relay_matrix = RelayMatrix(num_mcus)
        self.module_assignment = ModuleAssignment(
            num_outputs=2 * num_mcus,
            num_groups=4 * num_mcus,
            num_mcus=num_mcus,
        )
        self.rectifier_board = RectifierBoard(
            mcu_id, event_log,
            relay_matrix=self.relay_matrix,
            module_assignment=self.module_assignment,
        )

    def initialize(self, dt_index: int = 0) -> None:
        self.rectifier_board.initialize_relays(dt_index)

    def validate(self) -> list[str]:
        """Check matrix consistency. Returns list of violation strings."""
        violations: list[str] = []
        ma = self.module_assignment
        for o in range(ma.num_outputs):
            groups = ma.get_groups_for_output(o)
            if groups and not ma.is_contiguous(o):
                violations.append(f"Output {o}: non-contiguous groups {groups}")
        # Check no double-ownership
        for g in range(ma.num_groups):
            owners = [o for o in range(ma.num_outputs) if ma._matrix[o][g] == 1]
            if len(owners) > 1:
                violations.append(f"Group {g}: multiple owners {owners}")
        return violations

    def step(self, dt: float) -> None:
        self.rectifier_board.step(dt)

    def get_status(self) -> dict[str, Any]:
        return {
            "mcu_id": self.mcu_id,
            "rectifier_board": self.rectifier_board.get_status(),
            "relay_matrix": self.relay_matrix.to_dict(),
            "module_assignment": self.module_assignment.to_dict(),
        }
