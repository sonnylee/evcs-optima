"""TC-LOG-01 to TC-LOG-03: RelayEventLog tests."""

from simulation.log.relay_event import RelayEvent
from simulation.log.relay_event_log import RelayEventLog


def _evt(dt, relay_id="R1"):
    return RelayEvent(dt_index=dt, relay_id=relay_id,
                      event_type="SWITCHED", from_state="OPEN", to_state="CLOSED")


# TC-LOG-01: append and get_events
def test_append_and_get_events():
    log = RelayEventLog()
    log.append(_evt(1, "R1"))
    log.append(_evt(2, "R2"))
    log.append(_evt(3, "R1"))

    assert len(log.get_events()) == 3
    assert len(log.get_events("R1")) == 2
    assert len(log.get_events("R3")) == 0


# TC-LOG-02: get_events_at
def test_get_events_at():
    log = RelayEventLog()
    log.append(_evt(5, "R1"))
    log.append(_evt(5, "R2"))
    log.append(_evt(10, "R1"))

    assert len(log.get_events_at(5)) == 2
    assert len(log.get_events_at(99)) == 0


# TC-LOG-03: clear
def test_clear():
    log = RelayEventLog()
    log.append(_evt(1))
    log.append(_evt(2))
    log.clear()
    assert len(log) == 0


# Additional: RelayEvent.to_dict
def test_relay_event_to_dict():
    e = RelayEvent(dt_index=5, relay_id="R1", event_type="SWITCHED",
                   from_state="OPEN", to_state="CLOSED")
    d = e.to_dict()
    assert d["dt_index"] == 5
    assert d["relay_id"] == "R1"
    assert d["event_type"] == "SWITCHED"
    assert d["from_state"] == "OPEN"
    assert d["to_state"] == "CLOSED"
