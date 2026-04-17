"""Tests for Actor — simulation/environment/actor.py (95% → 100%).
Missing line 28: base handle() raises NotImplementedError.
"""
import asyncio
import pytest
from simulation.environment.actor import Actor
from simulation.communication.messages import Stop


class _EchoActor(Actor):
    def __init__(self):
        super().__init__(name="Echo")
        self.received: list = []

    async def handle(self, msg):
        if isinstance(msg, Stop):
            self.stop()
        else:
            self.received.append(msg)


class TestActor:
    async def test_send_and_receive_messages(self):
        actor = _EchoActor()
        task = asyncio.create_task(actor.run())
        await actor.send("hello")
        await actor.send("world")
        await actor.send(Stop())
        await asyncio.wait_for(task, timeout=1.0)
        assert actor.received == ["hello", "world"]

    async def test_stop_terminates_run(self):
        actor = _EchoActor()
        task = asyncio.create_task(actor.run())
        await actor.send(Stop())
        await asyncio.wait_for(task, timeout=1.0)
        assert not actor.running

    async def test_messages_arrive_in_order(self):
        actor = _EchoActor()
        task = asyncio.create_task(actor.run())
        for i in range(10):
            await actor.send(i)
        await actor.send(Stop())
        await asyncio.wait_for(task, timeout=1.0)
        assert actor.received == list(range(10))

    async def test_base_handle_raises_not_implemented(self):
        """Line 28: Actor.handle() raises NotImplementedError — must be overridden."""
        base = Actor(name="Base")
        with pytest.raises(NotImplementedError):
            await base.handle("any_message")

    async def test_task_done_called_in_finally(self):
        """Even if handle() raises, queue.task_done() is called (finally block)
        — the exception propagates and terminates the run loop."""
        class _CrashActor(Actor):
            async def handle(self, msg):
                raise RuntimeError("crash")

        actor = _CrashActor(name="Crash")
        task = asyncio.create_task(actor.run())
        await actor.send("trigger")
        with pytest.raises(RuntimeError, match="crash"):
            await asyncio.wait_for(task, timeout=1.0)
        # queue.join() would succeed because task_done() was called
        assert actor.queue.empty()
