from typing import Any

from simulation.base import SimulationModule
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.log.relay_event_log import RelayEventLog


class ChargingStation(SimulationModule):
    """Charging station shell — global container, no business logic."""

    def __init__(self, mcu_id: int, event_log: RelayEventLog):
        self.mcu_id = mcu_id
        self.rectifier_board = RectifierBoard(mcu_id, event_log)

    def initialize(self, dt_index: int = 0) -> None:
        self.rectifier_board.initialize_relays(dt_index)

    def step(self, dt: float) -> None:
        self.rectifier_board.step(dt)

    def get_status(self) -> dict[str, Any]:
        return {
            "mcu_id": self.mcu_id,
            "rectifier_board": self.rectifier_board.get_status(),
        }
