"""TC-INT-BR-01 to TC-INT-BR-04: Cross-MCU borrow protocol integration tests.

Per SPEC §10, each MCU owns its own ``ModuleAssignment``; helpers from
``conftest`` populate every MCU's mirror so the test setup mirrors what
the protocol layer would do at runtime.
"""

import asyncio
import pytest
from simulation.communication.messages import Stop
from tests.conftest import assign_across_station, get_owner_anywhere


# TC-INT-BR-01: MCU0 borrows G4 from MCU1 (granted)
@pytest.mark.asyncio
async def test_cross_mcu_borrow_granted(make_3mcu_system):
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    # Start MCU1 actor loop so it can process the borrow request
    task1 = asyncio.create_task(mcu1.run())
    try:
        # O0 on MCU0 has anchor at G0, set interval to [0,3] (all local)
        state = mcu0._output_states[0]
        state.interval_min = 0
        state.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        # Attempt cross-MCU borrow of G4 (MCU1's territory)
        await mcu0._try_borrow_async(state)

        # MCU0's O0 (abs 0) should now own G4 in MCU1's MA AND in MCU0's mirror
        assert station.boards[1].module_assignment.get_owner(4) == 0
        assert station.boards[0].module_assignment.get_owner(4) == 0
        assert state.interval_max == 4
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass


# TC-INT-BR-02: MCU1 denies G4 (already owned by MCU1's O2)
@pytest.mark.asyncio
async def test_cross_mcu_borrow_denied(make_3mcu_system):
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    task1 = asyncio.create_task(mcu1.run())
    try:
        # Pre-assign G4 to MCU1's O2 (output_idx=2)
        assign_across_station(station, 2, 4)

        state = mcu0._output_states[0]
        state.interval_min = 0
        state.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        await mcu0._try_borrow_async(state)

        # G4 should still be owned by output 2 in MCU1's authoritative MA.
        assert station.boards[1].module_assignment.get_owner(4) == 2
        assert state.interval_max == 3  # unchanged
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass


# TC-INT-BR-03: MCU0 returns G4 to MCU1
@pytest.mark.asyncio
async def test_cross_mcu_return(make_3mcu_system):
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    task1 = asyncio.create_task(mcu1.run())
    try:
        # First: borrow G4
        state = mcu0._output_states[0]
        state.interval_min = 0
        state.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        await mcu0._try_borrow_async(state)
        assert state.interval_max == 4

        # Now return: set up conditions for return (prefer cross-MCU)
        await mcu0._try_return_async(state)

        assert get_owner_anywhere(station, 4) is None
        assert state.interval_max == 3
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass


# TC-INT-BR-04: _sync_foreign_relays updates MCU1's bridge relay
@pytest.mark.asyncio
async def test_sync_foreign_relays(make_3mcu_system):
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

        # Borrow G4 — triggers _sync_foreign_relays on MCU1
        await mcu0._try_borrow_async(state)

        # The bridge relay between MCU0 and MCU1 should be active
        bridge = station.bridge_relay_between(0)  # MCU0's right bridge
        assert bridge is not None
        # Interval now spans across MCU boundary → bridge should be closed
        from simulation.hardware.relay import RelayState
        assert bridge.state == RelayState.CLOSED
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
