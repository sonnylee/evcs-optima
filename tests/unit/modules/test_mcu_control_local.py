"""TC-MCU-L-01 to TC-MCU-L-13: MCUControl local logic unit tests."""

import pytest
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.log.relay_event_log import RelayEventLog
from simulation.modules.mcu_control import MCUControl, GROUPS_PER_MCU
from simulation.modules.vehicle import VehicleState
from tests.conftest import make_vehicle


def _make_mcu(event_log, mcu_id=0, num_mcus=1, consecutive_threshold=1, station=None):
    """Helper to build an MCU. Per SPEC §10 the board owns its per-MCU
    RelayMatrix and ModuleAssignment instance — no shared global state."""
    board = RectifierBoard(
        mcu_id=mcu_id, event_log=event_log, num_mcus=num_mcus,
    )
    ma = board.module_assignment
    rm = board.relay_matrix
    mcu = MCUControl(
        mcu_id=mcu_id, board=board, module_assignment=ma,
        relay_matrix=rm, event_log=event_log, station=station,
        num_mcus=num_mcus, consecutive_threshold=consecutive_threshold,
    )
    return mcu, board, ma, rm


# TC-MCU-L-01: _local_to_global / _global_to_local
def test_local_global_conversion(event_log):
    mcu, _, _, _ = _make_mcu(event_log, mcu_id=1, num_mcus=3)
    # mcu_id=1 → group_base=4
    assert mcu._local_to_global(0) == 4
    assert mcu._local_to_global(3) == 7
    assert mcu._global_to_local(4) == 0
    assert mcu._global_to_local(7) == 3


# TC-MCU-L-02: _wrap — non-ring doesn't wrap
def test_wrap_no_ring(event_log):
    # num_mcus=2 → _ring_enabled=False
    mcu, _, _, _ = _make_mcu(event_log, mcu_id=0, num_mcus=2)
    assert mcu._ring_enabled is False
    assert mcu._wrap(-1) == -1
    assert mcu._wrap(8) == 8


# TC-MCU-L-03: _wrap — ring wraps correctly
def test_wrap_ring(event_log):
    # num_mcus=4 → _ring_enabled=True, num_groups_total=16
    mcu, _, _, _ = _make_mcu(event_log, mcu_id=0, num_mcus=4)
    assert mcu._ring_enabled is True
    assert mcu._wrap(-1) == 15
    assert mcu._wrap(16) == 0
    assert mcu._wrap(17) == 1


# TC-MCU-L-04: _is_local_group
def test_is_local_group(event_log):
    mcu, _, _, _ = _make_mcu(event_log, mcu_id=1, num_mcus=3)
    # mcu_id=1 → group_base=4, local groups = [4,5,6,7]
    assert mcu._is_local_group(4) is True
    assert mcu._is_local_group(7) is True
    assert mcu._is_local_group(3) is False
    assert mcu._is_local_group(8) is False


# TC-MCU-L-05: _tick_borrow_condition — accumulation logic
def test_tick_borrow_condition_accumulation(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=3)
    state = mcu._output_states[0]
    output = board.outputs[0]

    # Set up: vehicle connected with present == available, demand > available
    v = make_vehicle(max_power_kw=200.0)
    output.connect_vehicle(v)
    state.interval_min = 0
    state.interval_max = 1
    mcu._sync_output(0)  # available = G0+G1 = 125kW

    output.present_power_kw = 125.0
    v.max_require_power_kw = 200.0

    assert mcu._tick_borrow_condition(state, output) is False  # counter=1
    assert state.borrow_counter == 1
    assert mcu._tick_borrow_condition(state, output) is False  # counter=2
    assert state.borrow_counter == 2
    assert mcu._tick_borrow_condition(state, output) is True   # counter=3
    assert state.borrow_counter == 3

    # Break condition → counter resets
    output.present_power_kw = 100.0
    assert mcu._tick_borrow_condition(state, output) is False
    assert state.borrow_counter == 0


# TC-MCU-L-06: _tick_return_condition — present ≈ available doesn't trigger
def test_tick_return_condition_no_trigger(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle(max_power_kw=125.0)
    output.connect_vehicle(v)
    state.interval_min = 0
    state.interval_max = 1
    mcu._sync_output(0)  # available = 125kW

    output.present_power_kw = 125.0
    v.max_require_power_kw = 125.0
    state.return_counter = 999  # artificially high

    result = mcu._tick_return_condition(state, output, pre_available=125.0)
    # surplus = 125-125 = 0, edge power (G1=75kW), 0 < 75 → counter resets
    assert state.return_counter == 0
    assert result is False


# TC-MCU-L-07: _tick_return_condition — triggers return
def test_tick_return_condition_triggers(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle(max_power_kw=100.0)
    output.connect_vehicle(v)
    state.interval_min = 0
    state.interval_max = 2
    mcu._sync_output(0)  # available = 50+75+75 = 200kW
    # Assign groups so shrink target can be found
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    ma.assign_if_idle(0, 2)

    output.present_power_kw = 100.0
    v.max_require_power_kw = 100.0

    # surplus = 200-100=100, edge_power = G2(75kW), 100 >= 75 → trigger
    result = mcu._tick_return_condition(state, output, pre_available=200.0)
    assert result is True


# TC-MCU-L-08: _find_expansion_target — right-side priority
def test_find_expansion_target_right_priority(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 1
    # G2 is idle → should pick right (G2)
    target = mcu._find_expansion_target(state, allow_cross_mcu=False)
    assert target == 2


# TC-MCU-L-09: _find_shrink_target — not to anchor
def test_find_shrink_target_not_anchor(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 2
    # anchor=0, should shrink from max (2), not anchor
    target = mcu._find_shrink_target(state, prefer_cross_mcu=False)
    assert target == 2

    # Only anchor left → None
    state.interval_min = 0
    state.interval_max = 0
    target = mcu._find_shrink_target(state, prefer_cross_mcu=False)
    assert target is None


# TC-MCU-L-10: _apply_borrow updates interval and relay
def test_apply_borrow(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 1
    # Pre-assign G0, G1
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)

    initial_events = len(event_log)
    mcu._apply_borrow(state, target=2)

    assert state.interval_max == 2
    assert len(event_log) > initial_events  # relay switch events
    assert board.outputs[0].available_power_kw == 200.0  # G0(50)+G1(75)+G2(75)


# TC-MCU-L-11: _apply_return updates interval and relay
def test_apply_return(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 2
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    ma.assign_if_idle(0, 2)
    mcu._apply_global_relay_state()
    mcu._sync_output(0)

    mcu._apply_return(state, target=2)

    assert state.interval_max == 1
    assert ma.get_owner(2) is None


# TC-MCU-L-12: _force_return_group — from max end
def test_force_return_group(event_log):
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    # O0 holds [0,3], anchor=0, force return G3
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 3
    for g in range(4):
        ma.assign_if_idle(0, g)
    mcu._apply_global_relay_state()

    mcu._force_return_group(0, group_idx=3)
    assert state.interval_max == 2

    # Force return G2 from same output
    mcu._force_return_group(0, group_idx=2)
    assert state.interval_max == 1


# TC-MCU-L-13: get_status structure
def test_get_status(event_log):
    mcu, _, _, _ = _make_mcu(event_log)
    status = mcu.get_status()
    assert status["mcu_id"] == 0
    assert len(status["outputs"]) == 2
    assert "interval" in status["outputs"][0]


# ── Additional coverage tests ────────────────────────────────────────

def test_step_sync_borrow_return(event_log):
    """step() sync path triggers borrow then return over multiple calls."""
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle(max_power_kw=200.0)
    output.connect_vehicle(v)
    mcu.handle_vehicle_arrival(output_local_idx=0)

    # Advance relay phases through step() calls
    for _ in range(4):
        mcu.step(1.0)

    # Now output relay should be closed, available = 125kW
    output.present_power_kw = 125.0
    v.max_require_power_kw = 200.0

    # One more step triggers borrow (threshold=1)
    mcu.step(1.0)
    assert state.interval_max >= 2  # borrowed G2


def test_pre_step_guard_no_vehicle(event_log):
    """_pre_step_guard returns True when no vehicle connected."""
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    output = board.outputs[0]

    state.borrow_counter = 5
    state.return_counter = 5
    result = mcu._pre_step_guard(state, output)
    assert result is True
    assert state.borrow_counter == 0
    assert state.return_counter == 0


def test_initiate_departure_idempotent(event_log):
    """initiate_vehicle_departure is idempotent if already departing."""
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 1
    state.pending_intergroup_open = 1  # already departing

    mcu.initiate_vehicle_departure(0)
    assert state.pending_intergroup_open == 1  # not changed


def test_initiate_departure_no_interval(event_log):
    """initiate_vehicle_departure early exit if no interval."""
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    assert state.interval_min is None

    mcu.initiate_vehicle_departure(0)
    assert state.pending_intergroup_open == 0  # no change


def test_virtual_interval_contains_ring(event_log):
    """_virtual_interval_contains with ring wrap."""
    mcu, _, _, _ = _make_mcu(event_log, mcu_id=0, num_mcus=4)
    # Virtual interval [14, 17] wraps: physicals 14,15,0,1
    assert mcu._virtual_interval_contains(14, 17, 0) is True
    assert mcu._virtual_interval_contains(14, 17, 15) is True
    assert mcu._virtual_interval_contains(14, 17, 1) is True
    assert mcu._virtual_interval_contains(14, 17, 5) is False
    # None interval
    assert mcu._virtual_interval_contains(None, None, 0) is False


def test_virtual_interval_contains_linear(event_log):
    """_virtual_interval_contains without ring."""
    mcu, _, _, _ = _make_mcu(event_log, mcu_id=0, num_mcus=2)
    assert mcu._virtual_interval_contains(0, 3, 2) is True
    assert mcu._virtual_interval_contains(0, 3, 5) is False


def test_apply_borrow_left_expansion(event_log):
    """_apply_borrow with target < interval_min expands left."""
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[1]  # O1: anchor=G3
    state.interval_min = 2
    state.interval_max = 3
    ma.assign_if_idle(1, 2)
    ma.assign_if_idle(1, 3)

    mcu._apply_borrow(state, target=1)  # expand left
    assert state.interval_min == 1


def test_apply_return_from_min(event_log):
    """_apply_return with target == interval_min shrinks from left."""
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[1]  # O1: anchor=G3
    state.interval_min = 1
    state.interval_max = 3
    ma.assign_if_idle(1, 1)
    ma.assign_if_idle(1, 2)
    ma.assign_if_idle(1, 3)
    mcu._apply_global_relay_state()

    mcu._apply_return(state, target=1)
    assert state.interval_min == 2
    assert ma.get_owner(1) is None


def test_find_shrink_target_cross_mcu_preference(event_log):
    """_find_shrink_target prefers cross-MCU edges when requested."""
    mcu, board, ma, _ = _make_mcu(event_log, mcu_id=0, num_mcus=3)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 4  # G4 is cross-MCU

    # With prefer_cross_mcu=True, should pick G4 (cross-MCU, at max)
    target = mcu._find_shrink_target(state, prefer_cross_mcu=True)
    assert target == 4


def test_neighbor_by_mcu_id(event_log):
    """_neighbor_by_mcu_id returns correct neighbor or None."""
    from simulation.hardware.charging_station import ChargingStation
    el = event_log
    station = ChargingStation(mcu_id=0, event_log=el, num_mcus=3)
    station.initialize(dt_index=0)

    mcus = []
    for i in range(3):
        m = MCUControl(
            mcu_id=i, board=station.boards[i],
            module_assignment=station.boards[i].module_assignment,
            relay_matrix=station.boards[i].relay_matrix, event_log=el,
            station=station, num_mcus=3, consecutive_threshold=1,
        )
        mcus.append(m)
    mcus[0].right_neighbor = mcus[1]
    mcus[1].left_neighbor = mcus[0]
    mcus[1].right_neighbor = mcus[2]
    mcus[2].left_neighbor = mcus[1]

    assert mcus[0]._neighbor_by_mcu_id(1) is mcus[1]  # right
    assert mcus[1]._neighbor_by_mcu_id(0) is mcus[0]  # left
    assert mcus[0]._neighbor_by_mcu_id(2) is None  # not adjacent in linear

    # Single MCU always returns None
    mcu_single, _, _, _ = _make_mcu(el, mcu_id=0, num_mcus=1)
    assert mcu_single._neighbor_by_mcu_id(0) is None


def test_constructor_with_preassigned_groups(event_log):
    """MCUControl constructor picks up pre-existing assignments."""
    board = RectifierBoard(mcu_id=0, event_log=event_log, num_mcus=1)
    ma = board.module_assignment
    rm = board.relay_matrix
    # Pre-assign groups before constructing MCU
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)

    mcu = MCUControl(
        mcu_id=0, board=board, module_assignment=ma,
        relay_matrix=rm, event_log=event_log,
        num_mcus=1, consecutive_threshold=1,
    )
    state = mcu._output_states[0]
    assert state.interval_min == 0
    assert state.interval_max == 1
