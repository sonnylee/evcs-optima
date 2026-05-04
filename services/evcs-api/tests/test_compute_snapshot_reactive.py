"""Step F09.2 — verify ``compute_snapshot`` / ``compute_snapshot_async`` parity
and FR-09 capacity-warning surfacing.

Both entry points must produce equivalent ``VisualSnapshot`` results; the only
difference is whether the caller is in a sync or async context.

Note: ``compute_snapshot`` (sync) internally ``asyncio.run``s the async
version, so it MUST NOT be called from inside an async test. The parity
test below stays sync and drives the async version with its own
``asyncio.run`` to avoid nested event loops.
"""
from __future__ import annotations

import asyncio
from typing import List, Tuple

import pytest

from app.schemas.car_port import CarPortInput
from app.schemas.config import RecBdConfig, SystemConfig
from app.services.state_calculation_service import (
    compute_snapshot,
    compute_snapshot_async,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def basic_system() -> SystemConfig:
    """4 MCU × [50,75,75,50] = 1000 kW total — Sprint 1 envelope."""
    return SystemConfig(
        rec_bd_count=4,
        rec_bds=[RecBdConfig(id=i + 1, module_powers=[50, 75, 75, 50]) for i in range(4)],
    )


def _ports(specs: List[Tuple[int, int, int | None]]) -> List[CarPortInput]:
    return [
        CarPortInput(
            port_id=pid,
            max_required=mr,
            present=0,
            target=0,
            priority=pr,
        )
        for pid, mr, pr in specs
    ]


def _full(overrides: List[Tuple[int, int, int | None]]) -> List[CarPortInput]:
    base = {pid: (pid, 0, None) for pid in range(1, 9)}
    for pid, mr, pr in overrides:
        base[pid] = (pid, mr, pr)
    return _ports(list(base.values()))


@pytest.fixture
def single_port_125kw() -> List[CarPortInput]:
    return _full([(1, 125, None)])


# ── Tests ─────────────────────────────────────────────────────────────────


class TestComputeSnapshotReactive:
    """F09.2 — sync + async entry parity & capacity warnings."""

    def test_sync_entry_returns_visual_snapshot(self, basic_system, single_port_125kw):
        snap = compute_snapshot(basic_system, single_port_125kw)
        assert snap.total_power_kw >= 125
        assert len(snap.cars) == 8
        # Port 1 must be active.
        car1 = next(c for c in snap.cars if c.port_id == 1)
        assert car1.status == "Active"

    @pytest.mark.asyncio
    async def test_async_entry_returns_visual_snapshot(
        self, basic_system, single_port_125kw
    ):
        snap = await compute_snapshot_async(basic_system, single_port_125kw)
        assert snap.total_power_kw >= 125
        assert len(snap.cars) == 8

    def test_sync_and_async_produce_equivalent_results(
        self, basic_system, single_port_125kw
    ):
        sync_snap = compute_snapshot(basic_system, single_port_125kw)
        async_snap = asyncio.run(
            compute_snapshot_async(basic_system, single_port_125kw)
        )
        assert sync_snap.total_power_kw == async_snap.total_power_kw
        assert sync_snap.total_requested_kw == async_snap.total_requested_kw
        sync_active = [c.port_id for c in sync_snap.cars if c.status == "Active"]
        async_active = [c.port_id for c in async_snap.cars if c.status == "Active"]
        assert sync_active == async_active

    def test_overcapacity_emits_warning(self, basic_system):
        # 8 ports × 200 kW = 1600 kW > 1000 kW capacity.
        ports = _ports([(pid, 200, None) for pid in range(1, 9)])
        snap = compute_snapshot(basic_system, ports)
        assert any(
            "exceeds" in w.lower() and "max required" in w.lower()
            for w in snap.warnings
        ), f"expected MAX_REQUIRED_EXCEEDS_CAPACITY warning, got: {snap.warnings}"

    def test_undercapacity_no_warning(self, basic_system, single_port_125kw):
        snap = compute_snapshot(basic_system, single_port_125kw)
        assert not any(
            "exceeds" in w.lower() and "max required" in w.lower()
            for w in snap.warnings
        ), f"unexpected capacity warning under capacity: {snap.warnings}"
