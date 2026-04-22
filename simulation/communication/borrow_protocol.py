"""Borrow protocol — cross-MCU power borrow handshake."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from simulation.communication.messages import BorrowRequest

if TYPE_CHECKING:
    from simulation.environment.actor import Actor


async def send_borrow_request(
    neighbor: "Actor | None",
    from_mcu: int,
    group_idx: int,
    requester_output_idx: int,
    step_index: int,
) -> bool:
    """Send BorrowRequest to `neighbor` and await grant/deny.

    On grant, the responder has already reserved `group_idx` for
    `requester_output_idx` in the shared ModuleAssignment AND has resynced
    its own inter-group / bridge relays at `step_index` (SPEC §11: relay
    switching is owned exclusively by the local MCU).
    """
    if neighbor is None:
        return False
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    await neighbor.send(
        BorrowRequest(
            from_mcu=from_mcu,
            group_idx=group_idx,
            requester_output_idx=requester_output_idx,
            step_index=step_index,
            response=fut,
        )
    )
    return await fut
