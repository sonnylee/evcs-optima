"""Compute VisualSnapshot — FR-02, FR-03, FR-04, FR-05, FR-09.

Thin wrapper around ``WebSessionEngine`` (rebuild-engine snapshot strategy,
SPEC-WEB-API §3.2). Exposes :func:`compute_snapshot_async` (preferred for
FastAPI handlers) and a sync :func:`compute_snapshot` wrapper.
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
    """Async entry (preferred for FastAPI handlers).

    Builds a fresh ``WebSessionEngine``, settles to convergence, extracts a
    ``VisualSnapshot``, and appends FR-09 capacity warnings (soft, not a 422).
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
    """Sync entry wrapping :func:`compute_snapshot_async` via ``asyncio.run``.

    Must NOT be called from inside a running event loop.
    """
    return asyncio.run(compute_snapshot_async(system, car_ports, cycle=cycle))
