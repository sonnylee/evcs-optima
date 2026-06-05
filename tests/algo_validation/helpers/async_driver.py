"""``ExplorationDriver`` — single-step, interruptible mirror of
``SimulationEngine._driver_loop`` (``simulation_engine.py:159-196``).

Production ``run()`` drives the async actor loop to completion inside one
``asyncio.run``. The exploration harness instead needs to (a) advance one tick
at a time, (b) inject arrivals between ticks, and (c) inspect state after each
tick. This class wraps the *same* per-tick sequence as an awaitable ``tick()``,
with explicit actor lifecycle (``start_actors`` / ``stop_actors``) and an
``on_tick`` hook so the main loop can splice in the per-tick army + quiescence
check.

The body of ``tick()`` is copied line-for-line from ``_driver_loop``'s while
body so the two cannot silently diverge; ``test_driver_guard.py`` asserts
behavioural equivalence against production ``run()``.

Mirrors the async (multi-MCU) path only — ``run()`` for ``num_mcus <= 1`` takes
the synchronous ``_run_sync`` path, which the harness does not use.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional

from simulation.communication.messages import Stop, Tick

OnTick = Callable[["ExplorationDriver"], Optional[Awaitable[None]]]


class ExplorationDriver:
    def __init__(self, engine: Any, on_tick: Optional[OnTick] = None) -> None:
        self.engine = engine
        self.on_tick = on_tick
        self._actor_tasks: list[asyncio.Task] = []
        self._started = False

    # ── Actor lifecycle (mirrors _run_async: 148-157) ────────────────────

    async def start_actors(self) -> None:
        """Launch one actor task per MCU and run the ``_driver_loop`` preamble.

        Idempotent: a second call is a no-op.
        """
        if self._started:
            return
        engine = self.engine
        self._actor_tasks = [asyncio.create_task(m.run()) for m in engine.mcu_controls]
        self._started = True
        # _driver_loop preamble (simulation_engine.py:162-165): wire + prime
        # the traffic simulator if one is present. Exploration injects via the
        # low-level API instead, so this is a no-op when traffic_simulator is None.
        if engine.traffic_simulator is not None:
            engine.traffic_simulator.mcu_controls = engine.mcu_controls
            engine.traffic_simulator.prime_initial_arrivals()
            engine._sync_traffic_vehicles()

    # ── One tick (mirrors _driver_loop while body: 166-194) ──────────────

    async def tick(self) -> None:
        engine = self.engine
        tc = engine.time_controller
        dt = tc.dt

        # Align MCU clocks with the sim clock before arrivals dispatch
        # (simulation_engine.py:173-174).
        for mcu in engine.mcu_controls:
            mcu._step_index = tc.step_index
        if engine.traffic_simulator is not None:
            engine.traffic_simulator.step(dt)
            engine._sync_traffic_vehicles()
        # Vehicles step first (update SOC, negotiate power).
        for vehicle in engine.vehicles:
            vehicle.step(dt)
        engine._trigger_departures()

        # Broadcast Tick; collect per-MCU done events.
        done_events = [asyncio.Event() for _ in engine.mcu_controls]
        for mcu, ev in zip(engine.mcu_controls, done_events):
            await mcu.send(Tick(dt=dt, step_index=tc.step_index, done=ev))
        await asyncio.gather(*(e.wait() for e in done_events))

        # Drain any lingering protocol replies.
        await asyncio.sleep(0)

        engine.station.step(dt)
        engine._collect_snapshot()
        tc.tick()

        # Harness hook: per-tick army + quiescence check splice here, after the
        # step's state + snapshot are fully committed.
        if self.on_tick is not None:
            res = self.on_tick(self)
            if asyncio.iscoroutine(res):
                await res

    # ── Termination (mirrors _driver_loop guards: 166 + 195-196) ─────────

    def is_finished(self) -> bool:
        """``_driver_loop``'s combined stop condition: sim clock exhausted OR
        all charging complete. The harness adds coverage-based termination on
        top of this in the main loop."""
        engine = self.engine
        return engine.time_controller.is_finished() or engine._all_charging_complete()

    async def stop_actors(self) -> None:
        """Stop all MCU actors (mirrors _run_async finally: 154-157). Idempotent."""
        if not self._started:
            return
        engine = self.engine
        for m in engine.mcu_controls:
            await m.send(Stop())
        await asyncio.gather(*self._actor_tasks, return_exceptions=True)
        self._actor_tasks = []
        self._started = False
