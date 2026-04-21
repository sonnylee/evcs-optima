"""TC-INT-CR-01: ConflictRelease protocol integration test."""

import asyncio
import pytest
from simulation.communication.messages import Stop
from simulation.communication.return_protocol import send_conflict_release
from tests.conftest import assign_across_station, get_owner_anywhere


# TC-INT-CR-01: New vehicle conflict triggers ConflictRelease
@pytest.mark.asyncio
async def test_conflict_release_cross_mcu(make_3mcu_system):
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    task0 = asyncio.create_task(mcu0.run())
    task1 = asyncio.create_task(mcu1.run())
    try:
        # Setup: MCU0 O0 borrows G4 (MCU1's anchor for O2)
        state_o0 = mcu0._output_states[0]
        state_o0.interval_min = 0
        state_o0.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        await mcu0._try_borrow_async(state_o0)
        # Per-MCU MAs: MCU0 owns G4 in MCU0's mirror and in MCU1's authoritative MA.
        assert station.boards[0].module_assignment.get_owner(4) == 0
        assert station.boards[1].module_assignment.get_owner(4) == 0

        # MCU1 needs G4 for its O2 (new vehicle) — send ConflictRelease
        released = await send_conflict_release(mcu0, from_mcu=1, group_idx=4)

        assert released is True
        assert get_owner_anywhere(station, 4) is None
        assert state_o0.interval_max == 3  # MCU0 shrank
    finally:
        mcu0.stop()
        mcu1.stop()
        await mcu0.send(Stop())
        await mcu1.send(Stop())
        task0.cancel()
        task1.cancel()
        for t in [task0, task1]:
            try:
                await t
            except asyncio.CancelledError:
                pass
