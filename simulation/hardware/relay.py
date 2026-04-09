from enum import Enum
from typing import Any

from simulation.base import SimulationModule
from simulation.log.relay_event import RelayEvent
from simulation.log.relay_event_log import RelayEventLog


class RelayState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RelayType(str, Enum):
    OUTPUT_SWITCH = "OUTPUT_SWITCH"
    INTER_GROUP = "INTER_GROUP"


class Relay(SimulationModule):
    """DC relay — atomic switching, no intermediate states."""

    def __init__(
        self,
        relay_id: str,
        relay_type: RelayType,
        is_cross_mcu: bool,
        event_log: RelayEventLog,
        node_a: str,
        node_b: str,
        initial_state: RelayState = RelayState.OPEN,
    ):
        self.relay_id = relay_id
        self.relay_type = relay_type
        self.is_cross_mcu = is_cross_mcu
        self._event_log = event_log
        self.node_a = node_a
        self.node_b = node_b
        self.state = initial_state

    def switch(self, dt_index: int) -> None:
        old = self.state
        new = RelayState.CLOSED if old == RelayState.OPEN else RelayState.OPEN
        self.state = new
        self._event_log.append(RelayEvent(
            dt_index=dt_index,
            relay_id=self.relay_id,
            event_type="SWITCHED",
            from_state=old.value,
            to_state=new.value,
        ))

    def step(self, dt: float) -> None:
        pass  # relay switching is commanded, not time-driven

    def get_status(self) -> dict[str, Any]:
        return {
            "relay_id": self.relay_id,
            "type": self.relay_type.value,
            "state": self.state.value,
            "is_cross_mcu": self.is_cross_mcu,
            "node_a": self.node_a,
            "node_b": self.node_b,
        }
