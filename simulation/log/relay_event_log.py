from simulation.log.relay_event import RelayEvent


class RelayEventLog:
    """Singleton-style event log injected into all Relays at construction."""

    def __init__(self):
        self._events: list[RelayEvent] = []

    def append(self, event: RelayEvent) -> None:
        self._events.append(event)

    def get_events(self, relay_id: str | None = None) -> list[RelayEvent]:
        if relay_id is None:
            return list(self._events)
        return [e for e in self._events if e.relay_id == relay_id]

    def get_events_at(self, dt_index: int) -> list[RelayEvent]:
        return [e for e in self._events if e.dt_index == dt_index]

    def clear(self) -> None:
        self._events.clear()

    def __len__(self) -> int:
        return len(self._events)
