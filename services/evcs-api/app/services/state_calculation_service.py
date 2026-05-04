"""Compute VisualSnapshot — FR-02, FR-03, FR-04, FR-05, FR-09.

Phase 3 / Step F09.2: ``compute_snapshot`` now delegates to
``WebSessionEngine`` (rebuild-engine snapshot strategy, SPEC-WEB-API §3.2).
Two entry points are exposed:

- :func:`compute_snapshot_async` — preferred for FastAPI route handlers; uses
  ``WebSessionEngine.create()`` for full settle-loop convergence.
- :func:`compute_snapshot` — sync wrapper kept for sync callers
  (``step_planner``, ``evcs_core_adapter``); internally ``asyncio.run``s the
  async version.

The legacy greedy allocator (``allocate_packs`` and helpers) is **dead code**
after this step but left in place so the Cleanup step can remove it without
cascading edits. Do not call it from new code.
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple

from app.constants import (
    CAR_COLOR_ACTIVE,
    CAR_COLOR_INACTIVE,
    PACK_COLOR_IDLE,
    RELAY_COLOR_CLOSED,
    RELAY_COLOR_OPEN,
    STEP_KW,
)
from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.snapshot import (
    CarSnapshot,
    PackSnapshot,
    RecBdSnapshot,
    RelaySnapshot,
    VisualSnapshot,
)
from app.services.config_service import (
    bridge_relay_ids,
    car_port_ids_for_bd,
    home_rec_bd_for_port,
    module_pack_ranges,
    pick_palette,
)
from app.services.validation_service import validate_max_required_within_capacity
from app.services.web_session_engine import WebSessionEngine


PackKey = Tuple[int, int]  # (rec_bd_id, pack_index)


# ---------------------------------------------------------------------------
# Search order
# ---------------------------------------------------------------------------

def _home_order(pack_count: int, port_is_first: bool) -> List[int]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step.

    Anchor-based expansion within home REC BD.

    Port 1 (odd) anchors at pack 0 and expands right (SPEC §5.2).
    Port 2 (even) anchors at last pack and expands left.
    """

    if port_is_first:
        return list(range(pack_count))
    return list(range(pack_count - 1, -1, -1))


def _neighbor_rec_bds(home_bd: int, rec_bd_count: int) -> List[int]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step.

    Return neighbor REC BD ids in SPEC §2.2 borrow priority: right > left.

    For N=1: none. For N=2: just the other one. For N>=3 (ring): walks outward
    alternating right, left.
    """

    if rec_bd_count == 1:
        return []
    if rec_bd_count == 2:
        return [3 - home_bd]  # the other one

    out: List[int] = []
    for d in range(1, rec_bd_count):
        right = ((home_bd - 1 + d) % rec_bd_count) + 1
        left = ((home_bd - 1 - d) % rec_bd_count) + 1
        for n in (right, left):
            if n != home_bd and n not in out:
                out.append(n)
    return out


def _search_order(
    port_id: int, rec_bd_count: int, pack_counts: Dict[int, int]
) -> List[PackKey]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step."""
    home_bd = home_rec_bd_for_port(port_id)
    port_is_first = (port_id - 1) % 2 == 0

    order: List[PackKey] = [
        (home_bd, p) for p in _home_order(pack_counts[home_bd], port_is_first)
    ]
    for nb in _neighbor_rec_bds(home_bd, rec_bd_count):
        order.extend((nb, p) for p in range(pack_counts[nb]))
    return order


# ---------------------------------------------------------------------------
# Allocation
# ---------------------------------------------------------------------------

def _port_sort_key(cp: CarPortInput) -> Tuple[int, int, int]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step."""
    # (has_priority=0 if set else 1, priority_or_0, port_id) — priority-set first, then port_id.
    if cp.priority is not None:
        return (0, cp.priority, cp.port_id)
    return (1, 0, cp.port_id)


def allocate_packs(
    car_ports: List[CarPortInput], system: SystemConfig
) -> Dict[PackKey, int]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step.

    Return ``{(rec_bd_id, pack_index): owner_port_id}``.
    """

    pack_counts = {bd.id: bd.pack_count for bd in system.rec_bds}
    allocation: Dict[PackKey, int] = {}

    for cp in sorted(car_ports, key=_port_sort_key):
        if cp.max_required <= 0:
            continue
        need = cp.max_required // STEP_KW
        claimed = 0
        for key in _search_order(cp.port_id, system.rec_bd_count, pack_counts):
            if claimed >= need:
                break
            if key not in allocation:
                allocation[key] = cp.port_id
                claimed += 1

    return allocation


# ---------------------------------------------------------------------------
# Snapshot assembly
# ---------------------------------------------------------------------------

def _relay_color(state: str) -> str:
    return RELAY_COLOR_CLOSED if state == "Closed" else RELAY_COLOR_OPEN


def _build_output_relays(
    car_ports: List[CarPortInput], allocation: Dict[PackKey, int]
) -> List[RelaySnapshot]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step."""
    allocated_counts: Dict[int, int] = {}
    for owner in allocation.values():
        allocated_counts[owner] = allocated_counts.get(owner, 0) + 1

    relays: List[RelaySnapshot] = []
    for cp in sorted(car_ports, key=lambda c: c.port_id):
        home = home_rec_bd_for_port(cp.port_id)
        local_idx = (cp.port_id - 1) % 2 + 1
        state = "Closed" if allocated_counts.get(cp.port_id, 0) > 0 else "Open"
        relays.append(
            RelaySnapshot(
                id=f"M{home}.O{local_idx}",
                kind="output",
                state=state,
                color=_relay_color(state),
                owner_port_id=cp.port_id,
                rec_bd_id=home,
            )
        )
    return relays


def _build_inter_group_relays(
    system: SystemConfig, allocation: Dict[PackKey, int]
) -> List[RelaySnapshot]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step."""
    relays: List[RelaySnapshot] = []
    for bd in system.rec_bds:
        ranges = module_pack_ranges(bd.module_powers)
        for i in range(len(ranges) - 1):
            lo_l, hi_l = ranges[i]
            lo_r, hi_r = ranges[i + 1]
            left_owners = {allocation.get((bd.id, p)) for p in range(lo_l, hi_l)} - {None}
            right_owners = {allocation.get((bd.id, p)) for p in range(lo_r, hi_r)} - {None}
            # A port using both adjacent groups → relay must be closed to form the series path.
            state = "Closed" if (left_owners & right_owners) else "Open"
            relays.append(
                RelaySnapshot(
                    id=f"M{bd.id}.R{i + 2}",
                    kind="inter_group",
                    state=state,
                    color=_relay_color(state),
                    owner_port_id=None,
                    rec_bd_id=bd.id,
                )
            )
    return relays


def _build_bridge_relays(
    system: SystemConfig, allocation: Dict[PackKey, int]
) -> List[RelaySnapshot]:
    """[DEPRECATED — Phase 3 F09.2] Replaced by WebSessionEngine; will be removed in the Cleanup step."""
    ids = bridge_relay_ids(system.rec_bd_count)
    if not ids:
        return []
    relays: List[RelaySnapshot] = []
    for rid in ids:
        # 'B_{a}_{b}' — parse endpoints.
        _, a_s, b_s = rid.split("_")
        a, b = int(a_s), int(b_s)
        # Cross-REC-BD usage from either direction closes the bridge.
        cross = any(
            home_rec_bd_for_port(owner) == a and bd_id == b
            or home_rec_bd_for_port(owner) == b and bd_id == a
            for (bd_id, _), owner in allocation.items()
        )
        state = "Closed" if cross else "Open"
        relays.append(
            RelaySnapshot(
                id=rid,
                kind="bridge",
                state=state,
                color=_relay_color(state),
                owner_port_id=None,
                rec_bd_id=None,
            )
        )
    return relays


async def compute_snapshot_async(
    system: SystemConfig,
    car_ports: List[CarPortInput],
    cycle: bool = True,
) -> VisualSnapshot:
    """Async entry — preferred for FastAPI route handlers.

    Builds a fresh ``WebSessionEngine`` (rebuild-engine snapshot strategy,
    SPEC-WEB-API §3.2), drives the actor settle loop to convergence, then
    extracts a ``VisualSnapshot``. Appends FR-09 capacity warnings (soft —
    not a hard 422; FR-14 has its own hard ``TARGET_EXCEEDS_CAPACITY``).
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
    """Sync entry — kept for sync callers (``step_planner``, ``evcs_core_adapter``).

    Internally wraps :func:`compute_snapshot_async` with ``asyncio.run``.
    Must NOT be called from inside a running event loop. For async callers,
    use :func:`compute_snapshot_async` directly.
    """
    return asyncio.run(compute_snapshot_async(system, car_ports, cycle=cycle))
