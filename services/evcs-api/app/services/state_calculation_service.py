"""Compute VisualSnapshot — FR-02, FR-03, FR-04, FR-05, FR-09.

Thin wrapper around ``WebSessionEngine`` (rebuild-engine snapshot strategy,
SPEC-WEB-API §3.2). Two entry points are exposed:

- :func:`compute_snapshot_async` — preferred for FastAPI route handlers; uses
  ``WebSessionEngine.create()`` for full settle-loop convergence; appends
  FR-09 capacity warnings.
- :func:`compute_snapshot` — sync wrapper for legacy sync callers; internally
  ``asyncio.run``s the async version. Must not be called from inside a
  running event loop.

Note (Cleanup step): ``evcs_core_adapter`` was migrated off this module in
F14.2 and now uses ``WebSessionEngine.create()`` directly. ``compute_snapshot``
is currently called only by snapshot-route fallback paths.
"""
from __future__ import annotations

import asyncio
from typing import List

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.snapshot import VisualSnapshot
from app.services.validation_service import validate_max_required_within_capacity
from app.services.web_session_engine import WebSessionEngine


async def compute_snapshot_async(
    system: SystemConfig,
    car_ports: List[CarPortInput],
    cycle: bool = True,
) -> VisualSnapshot:
    """Async entry — preferred for FastAPI route handlers.

    Builds a fresh ``WebSessionEngine`` (rebuild-engine snapshot strategy,
    SPEC-WEB-API §3.2), drives the actor settle loop to convergence, then
    extracts a ``VisualSnapshot``. Appends FR-09 capacity warnings (soft —
    not a hard 422; FR-14 surfaces its own ``TARGET_EXCEEDS_CAPACITY``
    warning via the same channel).
    """
    engine = await WebSessionEngine.create(system, car_ports)
    snapshot = engine.to_visual_snapshot(palette_cycle=cycle)

    capacity_warnings = validate_max_required_within_capacity(car_ports, system)
    if capacity_warnings:
        snapshot.warnings.extend(w.message for w in capacity_warnings)

    return snapshot


def compute_snapshot(
    system: SystemConfig, car_ports: List[CarPortInput], cycle: bool = True
) -> VisualSnapshot:
    """Sync entry — kept for sync callers.

    Internally wraps :func:`compute_snapshot_async` with ``asyncio.run``.
    Must NOT be called from inside a running event loop. For async callers,
    use :func:`compute_snapshot_async` directly.
    """
    return asyncio.run(compute_snapshot_async(system, car_ports, cycle=cycle))
