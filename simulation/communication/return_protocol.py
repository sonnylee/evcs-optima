"""Return protocol — cross-MCU power return handshake."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from simulation.communication.messages import ConflictRelease, ReturnNotify

if TYPE_CHECKING:
    from simulation.environment.actor import Actor


async def send_return_notify(
    neighbor: "Actor | None", from_mcu: int, group_idx: int, step_index: int
) -> bool:
    """Tell neighbor we are releasing a group we had borrowed from it.

    On ack, the lender has cleared its own MA AND resynced its own relays
    at `step_index` (SPEC §11: relay switching is owned by the local MCU).
    """
    if neighbor is None:
        return True
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    await neighbor.send(
        ReturnNotify(
            from_mcu=from_mcu,
            group_idx=group_idx,
            step_index=step_index,
            response=fut,
        )
    )
    return await fut


async def send_conflict_release(
    neighbor: "Actor | None", from_mcu: int, group_idx: int
) -> bool:
    """Ask neighbor to forcibly release a group we need for a new vehicle."""
    if neighbor is None:
        return False
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    await neighbor.send(
        ConflictRelease(from_mcu=from_mcu, group_idx=group_idx, response=fut)
    )
    return await fut
