from dataclasses import dataclass


@dataclass(frozen=True)
class RelayEvent:
    dt_index: int
    relay_id: str
    event_type: str  # always "SWITCHED"
    from_state: str  # "OPEN" or "CLOSED"
    to_state: str    # "OPEN" or "CLOSED"

    def to_dict(self) -> dict:
        return {
            "dt_index": self.dt_index,
            "relay_id": self.relay_id,
            "event_type": self.event_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
        }
