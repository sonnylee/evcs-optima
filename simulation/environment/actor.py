"""Actor base class for asyncio+Queue messaging (SPEC §14)."""
from __future__ import annotations

import asyncio
from typing import Any


class Actor:
    """Base Actor — owns an asyncio.Queue and processes messages via handle()."""

    def __init__(self, name: str):
        self.name = name
        self.queue: asyncio.Queue = asyncio.Queue()
        self.running = True

    async def send(self, msg: Any) -> None:
        await self.queue.put(msg)

    async def run(self) -> None:
        while self.running:
            msg = await self.queue.get()
            try:
                await self.handle(msg)
            finally:
                self.queue.task_done()

    async def handle(self, msg: Any) -> None:
        raise NotImplementedError

    def stop(self) -> None:
        self.running = False
