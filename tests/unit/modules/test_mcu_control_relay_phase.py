"""TC-PHASE-01 to TC-PHASE-05: MCUControl relay phase state machine tests."""

import pytest
from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.hardware.relay import RelayState
from simulation.log.relay_event_log import RelayEventLog
from simulation.modules.mcu_control import MCUControl
from simulation.modules.vehicle import VehicleState
from tests.conftest import make_vehicle


def _make_mcu(event_log, mcu_id=0, num_mcus=1, consecutive_threshold=1):
    rm = RelayMatrix(num_mcus=num_mcus)
    ma = ModuleAssignment(num_outputs=2 * num_mcus, num_groups=4 * num_mcus, num_mcus=num_mcus)
    board = RectifierBoard(
        mcu_id=mcu_id, event_log=event_log,
        relay_matrix=rm, module_assignment=ma, num_mcus=num_mcus,
    )
    mcu = MCUControl(
        mcu_id=mcu_id, board=board, module_assignment=ma,
        relay_matrix=rm, event_log=event_log,
        num_mcus=num_mcus, consecutive_threshold=consecutive_threshold,
    )
    return mcu, board, ma, rm


# TC-PHASE-01: vehicle arrival — 3-phase startup relay sequence
def test_arrival_3phase_relay_sequence(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle()
    output.connect_vehicle(v)
    mcu.handle_vehicle_arrival(output_local_idx=0)

    # After arrival: pending_intergroup_close armed (=1)
    assert state.pending_intergroup_close == 1
    assert state.pending_output_relay_close == 0

    # Tick T+1: intergroup 1→2
    mcu._advance_relay_phases(state)
    assert state.pending_intergroup_close == 2

    # Tick T+2: intergroup fires (=0), output armed and immediately escalated (1→2)
    mcu._advance_relay_phases(state)
    assert state.pending_intergroup_close == 0
    assert state.pending_output_relay_close == 2

    # Tick T+3: output relay closes (available >= 125kW)
    mcu._advance_relay_phases(state)
    assert state.pending_output_relay_close == 0
    assert board.output_relays[0].state == RelayState.CLOSED


# TC-PHASE-02: available < 125kW — output relay stays open
def test_output_relay_blocked_insufficient_power(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle()
    output.connect_vehicle(v)
    mcu.handle_vehicle_arrival(output_local_idx=0)

    # Advance through intergroup phase
    mcu._advance_relay_phases(state)  # 1→2
    mcu._advance_relay_phases(state)  # intergroup fires, output escalated to 2

    # Disable all SMRs so _sync_output calculates < 125kW
    for g in board.groups:
        for smr in g.smrs:
            smr.enabled = False

    mcu._advance_relay_phases(state)
    # Output relay should NOT have closed (insufficient power)
    assert board.output_relays[0].state == RelayState.OPEN
    # pending still at 2 (waiting)
    assert state.pending_output_relay_close == 2


# TC-PHASE-03: vehicle departure — 2-phase relay sequence
def test_departure_2phase_relay_sequence(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    output = board.outputs[0]

    # Set up: vehicle connected, charged, relays closed
    v = make_vehicle()
    output.connect_vehicle(v)
    state.interval_min = 0
    state.interval_max = 1
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    mcu._apply_global_relay_state()
    mcu._sync_output(0)
    # Close output relay
    board.output_relays[0].switch(mcu._step_index)

    # Mark vehicle as complete
    v.state = VehicleState.COMPLETE

    mcu.initiate_vehicle_departure(0)
    assert state.pending_intergroup_open == 1

    # Advance: 1→2
    mcu._advance_relay_phases(state)
    assert state.pending_intergroup_open == 2

    # Advance: intergroup opens, output escalated to 2 in same call
    mcu._advance_relay_phases(state)
    assert state.pending_intergroup_open == 0
    assert state.pending_output_relay_open == 2

    # Advance: output opens, departure finalized
    mcu._advance_relay_phases(state)
    assert state.pending_output_relay_open == 0
    assert output.connected_vehicle is None


# TC-PHASE-04: departure — shared relay not opened
def test_departure_shared_relay_preserved(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)

    # O0 uses [0,1], O1 uses [2,3]
    # inter-group relay between G1-G2 is not used by either alone
    # But if both share a relay, it shouldn't be opened
    state_o0 = mcu._output_states[0]
    state_o1 = mcu._output_states[1]

    v0 = make_vehicle(vehicle_id="V0")
    v1 = make_vehicle(vehicle_id="V1")
    board.outputs[0].connect_vehicle(v0)
    board.outputs[1].connect_vehicle(v1)

    state_o0.interval_min = 0
    state_o0.interval_max = 1
    state_o1.interval_min = 2
    state_o1.interval_max = 3
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    ma.assign_if_idle(1, 2)
    ma.assign_if_idle(1, 3)
    mcu._apply_global_relay_state()

    # R_01 (inter_group_relays[0]) is needed by O0
    # R_23 (inter_group_relays[2]) is needed by O1
    r_01 = board.inter_group_relays[0]
    r_23 = board.inter_group_relays[2]

    # Close output relays
    board.output_relays[0].switch(mcu._step_index)
    board.output_relays[1].switch(mcu._step_index)

    # O0 departs
    v0.state = VehicleState.COMPLETE
    mcu.initiate_vehicle_departure(0)

    # Advance through departure
    for _ in range(4):
        mcu._advance_relay_phases(state_o0)

    # R_23 should still be closed (O1 needs it)
    assert r_23.state == RelayState.CLOSED


# TC-PHASE-05: pending period resets borrow/return counters
def test_pending_resets_counters(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle()
    output.connect_vehicle(v)
    mcu.handle_vehicle_arrival(output_local_idx=0)

    # Artificially set counters
    state.borrow_counter = 5
    state.return_counter = 5
    state.pending_intergroup_close = 2

    result = mcu._advance_relay_phases(state)
    assert result is True
    assert state.borrow_counter == 0
    assert state.return_counter == 0


# Additional: departure blocked when vehicle not COMPLETE
def test_departure_blocked_not_complete(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle()
    v.state = VehicleState.CHARGING  # NOT complete
    output.connect_vehicle(v)
    state.interval_min = 0
    state.interval_max = 1
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    mcu._apply_global_relay_state()
    board.output_relays[0].switch(mcu._step_index)

    mcu.initiate_vehicle_departure(0)
    # Advance through intergroup open phase
    mcu._advance_relay_phases(state)  # 1→2
    mcu._advance_relay_phases(state)  # intergroup opens, output 1→2
    mcu._advance_relay_phases(state)  # _finalize_departure called, but blocked

    # Vehicle still connected because it's not COMPLETE
    assert output.connected_vehicle is v
