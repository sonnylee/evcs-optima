"""Borrow protocol — cross-MCU power borrow handshake."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from simulation.communication.messages import BorrowRequest

if TYPE_CHECKING:
    from simulation.environment.actor import Actor


async def send_borrow_request(
    neighbor: "Actor | None", from_mcu: int, group_idx: int
) -> bool:
    """Send BorrowRequest to `neighbor` and await grant/deny.

    Returns True iff the neighbor granted use of `group_idx`.
    """
    if neighbor is None:
        return False
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    await neighbor.send(
        BorrowRequest(from_mcu=from_mcu, group_idx=group_idx, response=fut)
    )
    return await fut
