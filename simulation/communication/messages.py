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
    """MCU-A → neighbor: may I borrow `group_idx`? Reply via `response`."""
    from_mcu: int
    group_idx: int
    response: asyncio.Future  # -> bool (granted)


@dataclass
class ReturnNotify:
    """MCU-A → neighbor: I am releasing `group_idx`. Reply acknowledges."""
    from_mcu: int
    group_idx: int
    response: asyncio.Future  # -> bool (ack)


@dataclass
class ConflictRelease:
    """MCU-A → neighbor: a new vehicle needs `group_idx` you own, release it."""
    from_mcu: int
    group_idx: int
    response: asyncio.Future  # -> bool (released)
