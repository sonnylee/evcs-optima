"""Defaults and helpers for system configuration (FR-01 palette, FR-10 REC BD count, FR-11 module powers)."""
from __future__ import annotations

from typing import Dict, List, Tuple

from app.constants import (
    CAR_PORTS_PER_REC_BD,
    DEFAULT_PALETTE_CYCLE,
    EXTENDED_PALETTE,
    REC_BD_DEFAULT,
    STEP_KW,
)
from app.schemas.config import RecBdConfig, SystemConfig
from app.schemas.topology import ModuleGroupView, RecBdView, TopologyPreview


DEFAULT_MODULE_POWERS: List[int] = [50, 75, 75, 50]


def default_system_config(rec_bd_count: int = REC_BD_DEFAULT) -> SystemConfig:
    """Build the factory-default config: REC_BD_DEFAULT boards of 50/75/75/50 kW."""

    return SystemConfig(
        rec_bd_count=rec_bd_count,
        rec_bds=[
            RecBdConfig(id=i + 1, module_powers=list(DEFAULT_MODULE_POWERS))
            for i in range(rec_bd_count)
        ],
    )


def pick_palette(count: int, cycle: bool = True) -> List[str]:
    """Return ``count`` hex colors. FR-10 allows a fixed 4-color cycle or the extended palette."""

    if cycle:
        return [DEFAULT_PALETTE_CYCLE[i % len(DEFAULT_PALETTE_CYCLE)] for i in range(count)]
    return [EXTENDED_PALETTE[i % len(EXTENDED_PALETTE)] for i in range(count)]


def car_ports_for(rec_bd_count: int) -> int:
    return rec_bd_count * CAR_PORTS_PER_REC_BD


def home_rec_bd_for_port(port_id: int) -> int:
    """Port 1,2 → REC BD 1; Port 3,4 → REC BD 2; etc."""

    return (port_id - 1) // CAR_PORTS_PER_REC_BD + 1


def car_port_ids_for_bd(rec_bd_id: int) -> List[int]:
    """Two ports per REC BD: (2b-1, 2b)."""

    base = (rec_bd_id - 1) * CAR_PORTS_PER_REC_BD
    return [base + i + 1 for i in range(CAR_PORTS_PER_REC_BD)]


def module_pack_ranges(module_powers: List[int]) -> List[Tuple[int, int]]:
    """For module_powers=[50,75,75,50] → [(0,2),(2,5),(5,8),(8,10)] (end-exclusive)."""

    ranges: List[Tuple[int, int]] = []
    start = 0
    for p in module_powers:
        cnt = p // STEP_KW
        ranges.append((start, start + cnt))
        start += cnt
    return ranges


def bridge_relay_ids(rec_bd_count: int) -> List[str]:
    """SPEC §2.2: N=1 → no bridges; N=2 → one; N>=3 → ring of N."""

    if rec_bd_count <= 1:
        return []
    if rec_bd_count == 2:
        return ["B_1_2"]
    return [f"B_{i}_{(i % rec_bd_count) + 1}" for i in range(1, rec_bd_count + 1)]


def build_topology(system: SystemConfig, cycle: bool = True) -> TopologyPreview:
    """FR-01 + FR-10 + FR-11: derive the static layout (colors, packs, relay ids).

    This is a pure function of the config — no car_ports, no allocation, no dynamic state.
    """

    palette = pick_palette(system.rec_bd_count, cycle=cycle)
    rec_bds: List[RecBdView] = []

    for bd in system.rec_bds:
        ranges = module_pack_ranges(bd.module_powers)
        modules = [
            ModuleGroupView(
                group_index=i,
                power_kw=p,
                pack_count=p // STEP_KW,
                pack_indices=list(range(lo, hi)),
            )
            for i, (p, (lo, hi)) in enumerate(zip(bd.module_powers, ranges))
        ]
        rec_bds.append(
            RecBdView(
                id=bd.id,
                color=palette[bd.id - 1],
                total_capacity_kw=bd.total_capacity_kw,
                pack_count=bd.pack_count,
                modules=modules,
                # inter-group relays: R2..R(M) for an M-module REC BD (R1 is the left bridge).
                inter_group_relay_ids=[f"M{bd.id}.R{i + 2}" for i in range(len(bd.module_powers) - 1)],
                output_relay_ids=[f"M{bd.id}.O{i + 1}" for i in range(CAR_PORTS_PER_REC_BD)],
                car_port_ids=car_port_ids_for_bd(bd.id),
            )
        )

    return TopologyPreview(
        rec_bd_count=system.rec_bd_count,
        car_port_count=system.car_port_count,
        total_capacity_kw=system.total_capacity_kw,
        rec_bds=rec_bds,
        bridge_relay_ids=bridge_relay_ids(system.rec_bd_count),
    )
