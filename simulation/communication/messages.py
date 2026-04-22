"""Message types exchanged between MCU actors and the driver."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class Tick:
    """Driver → MCU: advance one simulation step."""
    dt: float
    step_index: int
    done: asyncio.Event


@dataclass
class Stop:
    """Driver → MCU: shut down the actor loop."""


@dataclass
class BorrowRequest:
    """MCU-A → neighbor: may I borrow `group_idx`? Reply via `response`.

    `requester_output_idx` is the global Output index that will own the group
    on grant, so the responder can atomically reserve it on the requester's
    behalf — closing the check→assign race across actors.

    `step_index` carries the requester's current tick so the lender can stamp
    its own relay-switch events at the same step (SPEC §11: only the owning
    MCU may switch its relays — the lender resyncs locally after granting).
    """
    from_mcu: int
    group_idx: int
    requester_output_idx: int
    step_index: int
    response: asyncio.Future  # -> bool (granted)


@dataclass
class ReturnNotify:
    """MCU-A → neighbor: I am releasing `group_idx`. Reply acknowledges.

    `step_index` carries the requester's current tick so the lender can stamp
    its own relay-switch events at the same step (SPEC §11: only the owning
    MCU may switch its relays — the lender resyncs locally after release).
    """
    from_mcu: int
    group_idx: int
    step_index: int
    response: asyncio.Future  # -> bool (ack)


@dataclass
class ConflictRelease:
    """MCU-A → neighbor: a new vehicle needs `group_idx` you own, release it."""
    from_mcu: int
    group_idx: int
    response: asyncio.Future  # -> bool (released)
