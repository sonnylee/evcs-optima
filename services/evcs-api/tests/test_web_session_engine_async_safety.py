"""Async-safety tests for ``WebSessionEngine`` — Step F09.1.5.

Verifies the dual-construction-pattern contract:

1. Sync ``__init__`` works in a plain sync context (no event loop).
2. Async ``create()`` works inside a running event loop (FastAPI route).
3. Sync ``__init__`` inside an async context **does not crash** — it just
   skips the settle loop and returns whatever the synchronous
   ``handle_vehicle_arrival`` managed. This pins the gotcha behaviour so
   future callers who forget ``create()`` see a partial allocation rather
   than a runtime error.
"""
from __future__ import annotations

from typing import List, Tuple

import pytest

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.services.web_session_engine import WebSessionEngine


# ── Local builders (mirror test_web_session_engine.py) ────────────────────

def _basic_system() -> SystemConfig:
    return SystemConfig.model_validate(
        {
            "rec_bd_count": 4,
            "rec_bds": [{"id": i + 1, "module_powers": [50, 75, 75, 50]} for i in range(4)],
        }
    )


def _ports(specs: List[Tuple[int, int, int | None]]) -> List[CarPortInput]:
    return [
        CarPortInput.model_validate(
            {"port_id": pid, "max_required": mr, "present": 0, "target": 0, "priority": pr}
        )
        for pid, mr, pr in specs
    ]


def _full_zero_ports(rec_bd_count: int = 4) -> List[CarPortInput]:
    return _ports([(pid, 0, None) for pid in range(1, rec_bd_count * 2 + 1)])


def _single_port_125() -> List[CarPortInput]:
    out = {pid: (pid, 0, None) for pid in range(1, 9)}
    out[1] = (1, 125, None)
    return _ports(list(out.values()))


def _two_ports_cross_mcu() -> List[CarPortInput]:
    """Port 1 = 350 kW (forces cross-MCU borrow). All other ports 0."""
    out = {pid: (pid, 0, None) for pid in range(1, 9)}
    out[1] = (1, 350, None)
    return _ports(list(out.values()))


# ── Tests ─────────────────────────────────────────────────────────────────


def test_sync_constructor_in_sync_context():
    """Sync constructor works in plain sync code (no running event loop)."""
    engine = WebSessionEngine(_basic_system(), _single_port_125())
    snap = engine.to_visual_snapshot()
    # 125 kW is anchor-fits — constructor sync path completes the allocation.
    assert snap.total_power_kw > 0
    car1 = next(c for c in snap.cars if c.port_id == 1)
    assert car1.allocated_kw >= 125


@pytest.mark.asyncio
async def test_create_in_async_context():
    """Async factory works inside a running event loop (FastAPI async route)."""
    engine = await WebSessionEngine.create(_basic_system(), _two_ports_cross_mcu())
    snap = engine.to_visual_snapshot()
    assert snap.total_power_kw > 0
    bridges = [r for r in snap.relays if r.kind == "bridge"]
    assert any(r.state == "Closed" for r in bridges), (
        "350 kW request must close at least one bridge after settle"
    )


@pytest.mark.asyncio
async def test_sync_constructor_in_async_context_no_settle():
    """Sync ``__init__`` inside an async context returns without settling.

    Documents the gotcha for any caller that forgets ``create()``: snapshot
    will reflect only what synchronous ``handle_vehicle_arrival`` managed
    (anchor + initial groups). This test pins that we don't crash and
    don't try to spin up a nested event loop.
    """
    # Note: NOT using ``await create(...)`` here — directly using __init__
    # from within an active event loop is the gotcha case.
    engine = WebSessionEngine(_basic_system(), _two_ports_cross_mcu())
    snap = engine.to_visual_snapshot()
    assert snap is not None  # primary assertion: didn't crash
    # Whatever allocation looks like, it must remain ≤ system capacity.
    assert snap.total_power_kw <= 1000
