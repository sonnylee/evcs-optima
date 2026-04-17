"""TC-RELAY-01 to TC-RELAY-06: Relay tests."""

from unittest.mock import MagicMock

from simulation.hardware.relay import Relay, RelayState, RelayType
from simulation.log.relay_event_log import RelayEventLog


def _make_relay(event_log, **kwargs):
    defaults = dict(
        relay_id="R1",
        relay_type=RelayType.INTER_GROUP,
        is_cross_mcu=False,
        event_log=event_log,
        node_a="G0",
        node_b="G1",
    )
    defaults.update(kwargs)
    return Relay(**defaults)


# TC-RELAY-01: initial state is OPEN
def test_initial_state_open(event_log):
    relay = _make_relay(event_log)
    assert relay.state == RelayState.OPEN


# TC-RELAY-02: switch OPEN → CLOSED
def test_switch_open_to_closed(event_log):
    relay = _make_relay(event_log)
    relay.switch(dt_index=1)

    assert relay.state == RelayState.CLOSED
    events = event_log.get_events("R1")
    assert len(events) == 1
    assert events[0].dt_index == 1
    assert events[0].event_type == "SWITCHED"
    assert events[0].from_state == "OPEN"
    assert events[0].to_state == "CLOSED"


# TC-RELAY-03: switch CLOSED → OPEN
def test_switch_closed_to_open(event_log):
    relay = _make_relay(event_log)
    relay.switch(dt_index=1)  # OPEN → CLOSED
    relay.switch(dt_index=2)  # CLOSED → OPEN

    assert relay.state == RelayState.OPEN
    events = event_log.get_events("R1")
    assert len(events) == 2
    assert events[1].from_state == "CLOSED"
    assert events[1].to_state == "OPEN"


# TC-RELAY-04: switch updates RelayMatrix
def test_switch_updates_relay_matrix(event_log):
    rm = MagicMock()
    relay = _make_relay(
        event_log,
        relay_matrix=rm,
        matrix_idx_a=0,
        matrix_idx_b=1,
    )
    relay.switch(dt_index=1)  # OPEN → CLOSED
    rm.set_state.assert_called_once_with(0, 1, 1)

    rm.reset_mock()
    relay.switch(dt_index=2)  # CLOSED → OPEN
    rm.set_state.assert_called_once_with(0, 1, 0)


# TC-RELAY-05: step() is no-op
def test_step_is_noop(event_log):
    relay = _make_relay(event_log)
    initial_state = relay.state
    relay.step(1.0)
    assert relay.state == initial_state
    assert len(event_log) == 0


# TC-RELAY-06: is_cross_mcu attribute
def test_is_cross_mcu_attribute(event_log):
    relay = _make_relay(event_log, relay_id="BR", is_cross_mcu=True)
    assert relay.is_cross_mcu is True


# Additional: get_status structure
def test_get_status(event_log):
    relay = _make_relay(event_log)
    status = relay.get_status()
    assert status["relay_id"] == "R1"
    assert status["state"] == "OPEN"
    assert status["type"] == "INTER_GROUP"
    assert status["is_cross_mcu"] is False
