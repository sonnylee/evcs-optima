"""Cross-MCU relay sync integration tests."""

import asyncio
import pytest
from simulation.communication.messages import Stop
from simulation.hardware.relay import RelayState
from tests.conftest import assign_across_station, get_owner_anywhere


@pytest.mark.asyncio
async def test_borrow_and_return_relay_consistency(make_3mcu_system):
    """After borrow and return, all relays return to their original state."""
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    task1 = asyncio.create_task(mcu1.run())
    try:
        # Record initial bridge state
        bridge = station.bridge_relay_between(0)
        assert bridge is not None
        assert bridge.state == RelayState.OPEN

        # Borrow G4
        state = mcu0._output_states[0]
        state.interval_min = 0
        state.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        await mcu0._try_borrow_async(state)
        assert bridge.state == RelayState.CLOSED

        # Return G4
        await mcu0._try_return_async(state)
        assert bridge.state == RelayState.OPEN
        assert get_owner_anywhere(station, 4) is None
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_multiple_borrows_relay_chain(make_3mcu_system):
    """Borrowing multiple groups across MCU boundary closes the right relays."""
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    task1 = asyncio.create_task(mcu1.run())
    try:
        state = mcu0._output_states[0]
        state.interval_min = 0
        state.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        # Borrow G4
        await mcu0._try_borrow_async(state)
        assert state.interval_max == 4

        # Borrow G5
        await mcu0._try_borrow_async(state)
        assert state.interval_max == 5
        assert station.boards[1].module_assignment.get_owner(5) == 0

        # MCU1's inter-group relay between G4-G5 should be closed
        mcu1_r01 = mcu1._board.inter_group_relays[0]  # G4-G5
        assert mcu1_r01.state == RelayState.CLOSED
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
