"""Allocate packs → compute VisualSnapshot (Phase 2; FR-02, FR-03, FR-04, FR-05, FR-09).

This is a simplified preview allocator used only by the Web UI for immediate
feedback. The real borrow/return protocol is in the Python core and is wired
through ``EvcsCoreAdapter`` in Phase 3.

Allocation rules (deliberately predictable, not an exact simulation):

* Ports are processed in priority order — priority asc, ties broken by port_id;
  ports without a priority sort after priority-set ports, also by port_id.
* Each port claims packs from its **home REC BD** first, then walks outward —
  right neighbor first, then left (SPEC §2.2 borrow priority).
* Ring (N ≥ 3) wraps around; linear (N = 2) only has one neighbor; N = 1 has none.
* Each pack goes to at most one port. Excess demand → ``TARGET_EXCEEDS_CAPACITY``-style warning.
"""
from __future__ import annotations

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


PackKey = Tuple[int, int]  # (rec_bd_id, pack_index)


# ---------------------------------------------------------------------------
# Search order
# ---------------------------------------------------------------------------

def _home_order(pack_count: int, port_is_first: bool) -> List[int]:
    """Anchor-based expansion within home REC BD.

    Port 1 (odd) anchors at pack 0 and expands right (SPEC §5.2).
    Port 2 (even) anchors at last pack and expands left.
    """

    if port_is_first:
        return list(range(pack_count))
    return list(range(pack_count - 1, -1, -1))


def _neighbor_rec_bds(home_bd: int, rec_bd_count: int) -> List[int]:
    """Return neighbor REC BD ids in SPEC §2.2 borrow priority: right > left.

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
    # (has_priority=0 if set else 1, priority_or_0, port_id) — priority-set first, then port_id.
    if cp.priority is not None:
        return (0, cp.priority, cp.port_id)
    return (1, 0, cp.port_id)


def allocate_packs(
    car_ports: List[CarPortInput], system: SystemConfig
) -> Dict[PackKey, int]:
    """Return ``{(rec_bd_id, pack_index): owner_port_id}``."""

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


def compute_snapshot(
    system: SystemConfig, car_ports: List[CarPortInput], cycle: bool = True
) -> VisualSnapshot:
    """Pure function: config + car_ports → full VisualSnapshot (FR-09 target)."""

    palette = pick_palette(system.rec_bd_count, cycle=cycle)
    color_by_bd = {i + 1: c for i, c in enumerate(palette)}

    allocation = allocate_packs(car_ports, system)

    # --- REC BD snapshots (FR-02) ------------------------------------------
    rec_bd_snaps: List[RecBdSnapshot] = []
    for bd in system.rec_bds:
        used = sum(1 for (b, _) in allocation if b == bd.id)
        rec_bd_snaps.append(
            RecBdSnapshot(
                id=bd.id,
                color=color_by_bd[bd.id],
                status="Occupied" if used > 0 else "Idle",
                power_kw=used * STEP_KW,
                used_packs=used,
                total_packs=bd.pack_count,
            )
        )

    # --- Pack snapshots (FR-03) --------------------------------------------
    pack_snaps: List[PackSnapshot] = []
    for bd in system.rec_bds:
        for idx in range(bd.pack_count):
            owner = allocation.get((bd.id, idx))
            if owner is None:
                pack_snaps.append(
                    PackSnapshot(
                        rec_bd_id=bd.id,
                        pack_index=idx,
                        in_use=False,
                        owner_port_id=None,
                        color=PACK_COLOR_IDLE,
                    )
                )
            else:
                # FR-03 interpretation: pack color = consuming port's home REC BD color.
                owner_home = home_rec_bd_for_port(owner)
                pack_snaps.append(
                    PackSnapshot(
                        rec_bd_id=bd.id,
                        pack_index=idx,
                        in_use=True,
                        owner_port_id=owner,
                        color=color_by_bd[owner_home],
                    )
                )

    # --- Relay snapshots (FR-04) -------------------------------------------
    relays: List[RelaySnapshot] = []
    relays.extend(_build_output_relays(car_ports, allocation))
    relays.extend(_build_inter_group_relays(system, allocation))
    relays.extend(_build_bridge_relays(system, allocation))

    # --- Car snapshots (FR-05) ---------------------------------------------
    allocated_per_port: Dict[int, int] = {}
    for owner in allocation.values():
        allocated_per_port[owner] = allocated_per_port.get(owner, 0) + STEP_KW

    car_snaps: List[CarSnapshot] = []
    for cp in sorted(car_ports, key=lambda c: c.port_id):
        allocated = allocated_per_port.get(cp.port_id, 0)
        active = cp.max_required > 0 and allocated > 0
        car_snaps.append(
            CarSnapshot(
                port_id=cp.port_id,
                rec_bd_id=home_rec_bd_for_port(cp.port_id),
                status="Active" if active else "Inactive",
                color=CAR_COLOR_ACTIVE if active else CAR_COLOR_INACTIVE,
                max_required=cp.max_required,
                allocated_kw=allocated,
                priority=cp.priority,
            )
        )

    # --- Warnings ----------------------------------------------------------
    warnings: List[str] = []
    total_requested = sum(cp.max_required for cp in car_ports)
    total_allocated = sum(allocated_per_port.values())
    if total_requested > total_allocated:
        warnings.append(
            f"Requested {total_requested} kW but only {total_allocated} kW allocated "
            f"(station capacity {system.total_capacity_kw} kW)."
        )
    for cp in car_ports:
        alloc = allocated_per_port.get(cp.port_id, 0)
        if cp.max_required > 0 and alloc < cp.max_required:
            warnings.append(
                f"Car Port {cp.port_id}: requested {cp.max_required} kW, allocated "
                f"{alloc} kW (lower priority starved)."
            )

    return VisualSnapshot(
        rec_bds=rec_bd_snaps,
        packs=pack_snaps,
        relays=relays,
        cars=car_snaps,
        total_power_kw=sum(s.power_kw for s in rec_bd_snaps),
        total_requested_kw=total_requested,
        warnings=warnings,
    )
