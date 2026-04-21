"""TC-BR-01 to TC-BR-05: MCUControl borrow/return unit tests."""

import asyncio
import pytest
from simulation.communication.messages import Tick
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.log.relay_event_log import RelayEventLog
from simulation.modules.mcu_control import MCUControl
from tests.conftest import make_vehicle


def _make_mcu(event_log, mcu_id=0, num_mcus=1, consecutive_threshold=1):
    """Per-MCU board owns its own RelayMatrix + ModuleAssignment (SPEC §10)."""
    board = RectifierBoard(
        mcu_id=mcu_id, event_log=event_log, num_mcus=num_mcus,
    )
    ma = board.module_assignment
    rm = board.relay_matrix
    mcu = MCUControl(
        mcu_id=mcu_id, board=board, module_assignment=ma,
        relay_matrix=rm, event_log=event_log,
        num_mcus=num_mcus, consecutive_threshold=consecutive_threshold,
    )
    return mcu, board, ma, rm


# TC-BR-01: _try_borrow_local — success borrow G2
def test_try_borrow_local_success(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 1
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    mcu._apply_global_relay_state()

    initial_events = len(event_log)
    mcu._try_borrow_local(state)

    assert state.interval_max == 2
    assert ma.get_owner(2) == 0  # output_idx=0 owns G2
    assert len(event_log) > initial_events


# TC-BR-02: _try_borrow_local — no available group (no-op)
def test_try_borrow_local_no_group(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    # O0 holds [0,1], O1 holds [2,3]
    state_o0 = mcu._output_states[0]
    state_o0.interval_min = 0
    state_o0.interval_max = 1
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)

    state_o1 = mcu._output_states[1]
    state_o1.interval_min = 2
    state_o1.interval_max = 3
    ma.assign_if_idle(1, 2)
    ma.assign_if_idle(1, 3)
    mcu._apply_global_relay_state()

    initial_events = len(event_log)
    mcu._try_borrow_local(state_o0)

    assert state_o0.interval_max == 1  # unchanged
    assert len(event_log) == initial_events


# TC-BR-03: _try_return_local — return G2
def test_try_return_local(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 2
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    ma.assign_if_idle(0, 2)
    mcu._apply_global_relay_state()
    mcu._sync_output(0)

    mcu._try_return_local(state)

    assert state.interval_max == 1
    assert ma.get_owner(2) is None


# TC-BR-04: _try_borrow_local doesn't cross MCU boundary
def test_try_borrow_local_no_cross_mcu(event_log):
    # 3-MCU, MCU0 O0 holds [0,3] (all local groups)
    mcu, board, ma, _ = _make_mcu(event_log, mcu_id=0, num_mcus=3)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 3
    for g in range(4):
        ma.assign_if_idle(0, g)
    mcu._apply_global_relay_state()

    # _try_borrow_local uses allow_cross_mcu=False → should NOT pick G4
    target = mcu._find_expansion_target(state, allow_cross_mcu=False)
    assert target is None  # no local groups available


# TC-BR-05: handle_vehicle_arrival — conflict force return
def test_handle_vehicle_arrival_conflict(event_log):
    mcu, board, ma, _ = _make_mcu(event_log)
    # O1 borrowed G1 (crossing into O0's territory)
    state_o1 = mcu._output_states[1]
    state_o1.interval_min = 1
    state_o1.interval_max = 3
    ma.assign_if_idle(1, 1)
    ma.assign_if_idle(1, 2)
    ma.assign_if_idle(1, 3)
    mcu._apply_global_relay_state()

    # O0 new vehicle arrives — needs G0 and G1
    v = make_vehicle()
    board.outputs[0].connect_vehicle(v)
    mcu.handle_vehicle_arrival(output_local_idx=0)

    # O0 should now own G0 and G1
    assert ma.get_owner(0) == 0
    assert ma.get_owner(1) == 0
    # O1 should have shrunk — lost G1
    assert state_o1.interval_min == 2


# ── Additional coverage tests ────────────────────────────────────────

def test_handle_vehicle_arrival_o1(event_log):
    """handle_vehicle_arrival for O1 uses G2/G3."""
    mcu, board, ma, _ = _make_mcu(event_log)
    state_o1 = mcu._output_states[1]

    v = make_vehicle()
    board.outputs[1].connect_vehicle(v)
    mcu.handle_vehicle_arrival(output_local_idx=1)

    assert ma.get_owner(2) == 1
    assert ma.get_owner(3) == 1
    assert state_o1.interval_min == 2
    assert state_o1.interval_max == 3


@pytest.mark.asyncio
async def test_handle_tick_borrow(event_log):
    """_handle_tick async path processes borrow."""
    mcu, board, ma, _ = _make_mcu(event_log, consecutive_threshold=1)
    state = mcu._output_states[0]
    output = board.outputs[0]

    v = make_vehicle(max_power_kw=200.0)
    output.connect_vehicle(v)
    mcu.handle_vehicle_arrival(output_local_idx=0)

    # Advance relay phases to completion (4 ticks)
    for step_idx in range(1, 5):
        done = asyncio.Event()
        tick = Tick(dt=1.0, step_index=step_idx, done=done)
        await mcu._handle_tick(tick)
        assert done.is_set()

    # Set up borrow condition
    output.present_power_kw = 125.0
    v.max_require_power_kw = 200.0

    done = asyncio.Event()
    tick = Tick(dt=1.0, step_index=5, done=done)
    await mcu._handle_tick(tick)
    assert done.is_set()
    # Should have borrowed G2 (local)
    assert state.interval_max >= 2


def test_try_return_local_no_target(event_log):
    """_try_return_local when only anchor → no-op."""
    mcu, board, ma, _ = _make_mcu(event_log)
    state = mcu._output_states[0]
    state.interval_min = 0
    state.interval_max = 0  # only anchor, can't shrink

    initial_max = state.interval_max
    mcu._try_return_local(state)
    assert state.interval_max == initial_max
