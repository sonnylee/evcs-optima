"""Progressive-demand control-step planner (Z.2 — FR-14 / FR-15).

SPEC §11 ordering comes entirely from ``mcu_control``: every snapshot is a
settled steady state. The planner walks ``max_required`` from ``present`` to
``target`` in ``STEP_KW`` increments, settles each via
``WebSessionEngine.create()``, dedups consecutive snapshots with identical
relay+pack state, then emits one ``ControlStep`` per changed relay between
kept pairs.

References: ``docs/SPEC-WEB-API.md`` §3.3, ``docs/SPEC.md`` §11.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

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
from app.schemas.control_step import ControlStep
from app.schemas.snapshot import (
    CarSnapshot,
    PackSnapshot,
    RecBdSnapshot,
    RelaySnapshot,
    VisualSnapshot,
)
from app.services.config_service import (
    home_rec_bd_for_port,
    module_pack_ranges,
)


# ---------------------------------------------------------------------------
# Step 1 — Per-port classification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Phase:
    ARRIVAL = "arrival"        # present == 0 and target > 0
    DEPARTURE = "departure"    # present > 0 and target == 0
    INCREASE = "increase"      # 0 < present < target
    DECREASE = "decrease"      # 0 < target < present
    NO_CHANGE = "no_change"    # present == target


def _phase_of(cp: CarPortInput) -> str:
    if cp.present == cp.target:
        return _Phase.NO_CHANGE
    if cp.present == 0 and cp.target > 0:
        return _Phase.ARRIVAL
    if cp.present > 0 and cp.target == 0:
        return _Phase.DEPARTURE
    if cp.target > cp.present:
        return _Phase.INCREASE
    return _Phase.DECREASE


def _prio_key(cp: CarPortInput) -> int:
    return cp.priority if cp.priority is not None else 10**9


# ---------------------------------------------------------------------------
# Step 2 — Relay diff
# ---------------------------------------------------------------------------

@dataclass
class _RelayFlip:
    relay_id: str
    from_state: str
    to_state: str
    kind: str                        # "output" | "inter_group" | "bridge"
    owner_port_id: Optional[int]     # for output relays
    rec_bd_id: Optional[int]         # for output / inter_group
    port: int                        # the port this flip is attributed to


def _relay_diff(
    initial: VisualSnapshot, final: VisualSnapshot
) -> List[Tuple[RelaySnapshot, RelaySnapshot]]:
    """Pair relays by id; keep only those whose state differs."""
    init_by_id = {r.id: r for r in initial.relays}
    diffs: List[Tuple[RelaySnapshot, RelaySnapshot]] = []
    for fr in final.relays:
        ir = init_by_id.get(fr.id)
        if ir is None:
            # Shouldn't happen if both snapshots come from the same SystemConfig
            continue
        if ir.state != fr.state:
            diffs.append((ir, fr))
    return diffs


# ---------------------------------------------------------------------------
# Helpers — pack ↔ group ↔ relay topology
# ---------------------------------------------------------------------------

def _pack_to_group(system: SystemConfig, bd_id: int, pack_idx: int) -> int:
    rec_bd = next(b for b in system.rec_bds if b.id == bd_id)
    for g_idx, (lo, hi) in enumerate(module_pack_ranges(rec_bd.module_powers)):
        if lo <= pack_idx < hi:
            return g_idx
    raise ValueError(f"pack_idx {pack_idx} not in REC BD {bd_id}")


def _anchor_group(system: SystemConfig, port_id: int) -> Tuple[int, int]:
    """Return (anchor_bd_id, anchor_group_idx) for a port.

    Port's home REC BD = ceil(port_id / 2). First port (odd) anchors at
    group 0; second port (even) anchors at the last group.
    """
    home = home_rec_bd_for_port(port_id)
    is_first = (port_id - 1) % 2 == 0
    rec_bd = next(b for b in system.rec_bds if b.id == home)
    last_group = len(rec_bd.module_powers) - 1
    return (home, 0 if is_first else last_group)


def _bridge_endpoints(bridge_id: str) -> Tuple[int, int]:
    """B_a_b → (a, b). a is the left side (= b - 1 mod N)."""
    _, a, b = bridge_id.split("_")
    return int(a), int(b)


def _output_relay_id(port_id: int) -> str:
    home = home_rec_bd_for_port(port_id)
    local_idx = (port_id - 1) % 2 + 1
    return f"M{home}.O{local_idx}"


def _packs_with_owner(snap: VisualSnapshot, port_id: int) -> Set[Tuple[int, int]]:
    return {(p.rec_bd_id, p.pack_index) for p in snap.packs if p.owner_port_id == port_id}


# ---------------------------------------------------------------------------
# Flip attribution — decide which port "owns" each flip for ordering
# ---------------------------------------------------------------------------

def _attribute_flip(
    pre: RelaySnapshot,
    post: RelaySnapshot,
    initial: VisualSnapshot,
    final: VisualSnapshot,
    ports_by_id: Dict[int, CarPortInput],
    system: SystemConfig,
) -> int:
    """Decide which port_id this flip is attributed to.

    Output relays use their own owner_port_id. Inter-group/bridge relays use
    adjacent pack owners (final if closing, initial if opening); ties favour
    the departing port (release-then-engage).
    """
    if post.kind == "output":
        # Should always have owner_port_id
        return post.owner_port_id or 0

    closing = post.state == "Closed"
    candidates_final = _adjacent_pack_owners(post, final, system)
    candidates_initial = _adjacent_pack_owners(pre, initial, system)

    if closing:
        # In final, this relay is closed because some port spans both sides.
        owners = candidates_final or candidates_initial
    else:
        # Opening: in initial, the relay was closed because some port spanned.
        owners = candidates_initial or candidates_final

    if not owners:
        return 0

    # Tie-break: prefer departing port (release-then-engage)
    departing = [p for p in owners if p in ports_by_id and _phase_of(ports_by_id[p]) == _Phase.DEPARTURE]
    if departing:
        return departing[0]
    return min(owners)


def _adjacent_pack_owners(
    relay: RelaySnapshot, snap: VisualSnapshot, system: SystemConfig,
) -> List[int]:
    """Owners of packs immediately adjacent to a non-output relay."""
    if relay.kind == "inter_group":
        # M{bd}.R{i+2} connects group i and group i+1.
        bd_id = relay.rec_bd_id
        try:
            r_num = int(relay.id.split(".R")[1])
        except (ValueError, IndexError):
            return []
        left_g = r_num - 2
        right_g = r_num - 1
        owners: List[int] = []
        for p in snap.packs:
            if p.rec_bd_id != bd_id or p.owner_port_id is None:
                continue
            g = _pack_to_group(system, p.rec_bd_id, p.pack_index)
            if g != left_g and g != right_g:
                continue
            owners.append(p.owner_port_id)
        # Dedup, preserve order
        return list(dict.fromkeys(owners))
    if relay.kind == "bridge":
        a, b = _bridge_endpoints(relay.id)
        owners = []
        for p in snap.packs:
            if p.rec_bd_id in (a, b) and p.owner_port_id is not None:
                owners.append(p.owner_port_id)
        return list(dict.fromkeys(owners))
    return []


# ---------------------------------------------------------------------------
# Progressive demand sequence (Z.2 — replaces SPEC §11 sort)
# ---------------------------------------------------------------------------

_MAX_PROGRESSIVE_STEPS = 40  # safety bound; scenario 2 expects ~8-15


def _progressive_demand(
    initial: List[CarPortInput], step_index: int
) -> List[CarPortInput]:
    """Per-port ``max_required`` advanced from ``present`` toward ``target`` by
    ``step_index * STEP_KW`` (clamped to the present↔target range).
    """
    result: List[CarPortInput] = []
    for cp in initial:
        delta = step_index * STEP_KW
        if cp.target > cp.present:
            direction = 1
        elif cp.target < cp.present:
            direction = -1
        else:
            direction = 0
        candidate = cp.present + direction * delta
        lo = min(cp.present, cp.target)
        hi = max(cp.present, cp.target)
        new_max = max(lo, min(hi, candidate))
        result.append(cp.model_copy(update={"max_required": new_max}))
    return result


def _target_reached(ports: List[CarPortInput]) -> bool:
    return all(cp.max_required == cp.target for cp in ports)


async def _generate_progressive_snapshots(
    system: SystemConfig,
    car_ports: List[CarPortInput],
) -> List[Tuple[List[CarPortInput], VisualSnapshot]]:
    """Walk demand from present→target in STEP_KW increments; capture each
    settled snapshot. SPEC §11 ordering is enforced by mcu_control inside
    each ``WebSessionEngine.create()`` call.
    """
    from app.services.web_session_engine import WebSessionEngine

    snapshots: List[Tuple[List[CarPortInput], VisualSnapshot]] = []
    step = 0
    prev_demand: Optional[Tuple[int, ...]] = None
    prev_snap: Optional[VisualSnapshot] = None
    while True:
        ports_at_step = _progressive_demand(car_ports, step)
        demand = tuple(cp.max_required for cp in ports_at_step)
        # optimisation: skip rebuild if demand unchanged
        # WebSessionEngine.create() is deterministic, so an identical demand
        # vector settles to the identical snapshot — reuse the previous one
        # instead of rebuilding the engine for that port set.
        if demand == prev_demand and prev_snap is not None:
            snap = prev_snap
        else:
            engine = await WebSessionEngine.create(system, ports_at_step)
            snap = engine.to_visual_snapshot()
            prev_demand = demand
            prev_snap = snap
        snapshots.append((ports_at_step, snap))
        if _target_reached(ports_at_step):
            break
        step += 1
        if step > _MAX_PROGRESSIVE_STEPS:
            break
    return snapshots


def _dedup_snapshots(
    snapshots: List[Tuple[List[CarPortInput], VisualSnapshot]],
) -> List[Tuple[List[CarPortInput], VisualSnapshot]]:
    """Drop consecutive snapshots whose ``(relay_state, pack_owner)`` tuple
    matches the previous kept snapshot. Preserves the first occurrence.
    """
    if not snapshots:
        return []

    def _key(snap: VisualSnapshot) -> tuple:
        relays = tuple(sorted((r.id, r.state) for r in snap.relays))
        packs = tuple(
            sorted((p.rec_bd_id, p.pack_index, p.owner_port_id) for p in snap.packs)
        )
        return (relays, packs)

    deduped = [snapshots[0]]
    prev_key = _key(snapshots[0][1])
    for ports, snap in snapshots[1:]:
        key = _key(snap)
        if key != prev_key:
            deduped.append((ports, snap))
            prev_key = key
    return deduped


# ---------------------------------------------------------------------------
# Step 5 — Snapshot stitching
# ---------------------------------------------------------------------------

def _stitch_snapshot(
    system: SystemConfig,
    car_ports: List[CarPortInput],
    initial: VisualSnapshot,
    final: VisualSnapshot,
    applied: Set[str],
    all_flips: List[_RelayFlip],
) -> VisualSnapshot:
    """Build a mid-state snapshot blending ``initial`` and ``final``.

    Relays take their final value if their flip is applied, else initial.
    Packs switch to final ownership only once the gating relay flips are all
    applied. Cars and rec_bds are derived from the resulting packs/relays.
    """
    final_relay = {r.id: r for r in final.relays}
    initial_relay = {r.id: r for r in initial.relays}
    initial_pack = {(p.rec_bd_id, p.pack_index): p for p in initial.packs}
    final_pack = {(p.rec_bd_id, p.pack_index): p for p in final.packs}
    flips_by_id = {f.relay_id: f for f in all_flips}
    ports_by_id = {p.port_id: p for p in car_ports}

    # --- Relays ---------------------------------------------------------
    new_relays = [
        (final_relay[r.id] if r.id in applied else r).model_copy()
        for r in initial.relays
    ]

    # --- Packs ----------------------------------------------------------
    new_packs: List[PackSnapshot] = []
    for ip in initial.packs:
        key = (ip.rec_bd_id, ip.pack_index)
        fp = final_pack.get(key, ip)
        if ip.owner_port_id == fp.owner_port_id:
            new_packs.append(ip.model_copy())
            continue
        # Owner transition. Decide based on the trigger relay.
        new_owner = _resolve_pack_owner(
            ip, fp, system, applied, flips_by_id, ports_by_id
        )
        if new_owner == fp.owner_port_id:
            new_packs.append(fp.model_copy())
        else:
            new_packs.append(ip.model_copy())

    # --- Build helpers from new packs/relays ----------------------------
    relay_by_id = {r.id: r for r in new_relays}
    final_car_by_pid = {c.port_id: c for c in final.cars}
    initial_car_by_pid = {c.port_id: c for c in initial.cars}

    pack_owner_count: Dict[int, int] = {}
    for pk in new_packs:
        if pk.owner_port_id is not None:
            pack_owner_count[pk.owner_port_id] = pack_owner_count.get(pk.owner_port_id, 0) + 1

    # --- Cars (FR-05) ---------------------------------------------------
    new_cars: List[CarSnapshot] = []
    for ic in initial.cars:
        fc = final_car_by_pid.get(ic.port_id, ic)
        out_id = _output_relay_id(ic.port_id)
        out_relay = relay_by_id.get(out_id)
        out_closed = out_relay is not None and out_relay.state == "Closed"
        max_req = fc.max_required  # follow final's value (target-driven)
        owned_packs = pack_owner_count.get(ic.port_id, 0)
        allocated_kw = owned_packs * STEP_KW if out_closed else 0
        active = out_closed and max_req > 0
        new_cars.append(
            CarSnapshot(
                port_id=ic.port_id,
                rec_bd_id=ic.rec_bd_id,
                status="Active" if active else "Inactive",
                color=CAR_COLOR_ACTIVE if active else CAR_COLOR_INACTIVE,
                max_required=max_req,
                allocated_kw=allocated_kw,
                priority=fc.priority if fc.priority is not None else ic.priority,
            )
        )

    # --- REC BDs (FR-02) ------------------------------------------------
    used_per_bd: Dict[int, int] = {}
    for pk in new_packs:
        if pk.owner_port_id is not None:
            used_per_bd[pk.rec_bd_id] = used_per_bd.get(pk.rec_bd_id, 0) + 1
    new_recbds: List[RecBdSnapshot] = []
    for ib in initial.rec_bds:
        used = used_per_bd.get(ib.id, 0)
        new_recbds.append(
            RecBdSnapshot(
                id=ib.id,
                color=ib.color,
                status="Occupied" if used > 0 else "Idle",
                power_kw=used * STEP_KW,
                used_packs=used,
                total_packs=ib.total_packs,
            )
        )

    return VisualSnapshot(
        rec_bds=new_recbds,
        packs=new_packs,
        relays=new_relays,
        cars=new_cars,
        total_power_kw=sum(c.allocated_kw for c in new_cars),
        total_requested_kw=final.total_requested_kw,
        warnings=[],
    )


def _resolve_pack_owner(
    ip: PackSnapshot,
    fp: PackSnapshot,
    system: SystemConfig,
    applied: Set[str],
    flips_by_id: Dict[str, _RelayFlip],
    ports_by_id: Dict[int, CarPortInput],
) -> Optional[int]:
    """Decide who owns a transitioning pack at the current applied state.

    Identifies the candidate port and its gating relay flips: when claiming,
    all gating flips must be applied to use the final owner; when releasing,
    any applied gating flip switches to the final owner.
    """
    candidate_port: Optional[int] = fp.owner_port_id or ip.owner_port_id
    if candidate_port is None:
        return None
    cp = ports_by_id.get(candidate_port)
    if cp is None:
        return ip.owner_port_id

    pack_bd = ip.rec_bd_id
    pack_group = _pack_to_group(system, pack_bd, ip.pack_index)
    anchor_bd, anchor_group = _anchor_group(system, candidate_port)

    # Determine the "gating" relay(s) — relays in this port's flip chain
    # that are needed to connect anchor → pack.
    port_flips = [f for f in flips_by_id.values() if f.port == candidate_port]
    gating: Set[str] = set()

    if pack_bd == anchor_bd:
        # Same REC BD — gating = inter-group relays between anchor_group and pack_group
        lo, hi = sorted([anchor_group, pack_group])
        for f in port_flips:
            if f.kind == "inter_group" and f.rec_bd_id == pack_bd:
                # Relay R(k+2) connects group k and k+1; gating if k in [lo, hi-1]
                try:
                    k = int(f.relay_id.split(".R")[1]) - 2
                except (ValueError, IndexError):
                    continue
                if lo <= k < hi:
                    gating.add(f.relay_id)
    else:
        # Cross-REC-BD — gating = bridges between home and pack's REC BD,
        # plus inter-group relays in BOTH home and target REC BD that belong to this port.
        for f in port_flips:
            if f.kind in ("inter_group", "bridge"):
                gating.add(f.relay_id)

    # Decision: arrival-style (claiming, ip.owner=None) → all gating must be applied
    # to transfer to final.
    # Departure-style (releasing, fp.owner=None) → if any gating flip applied,
    # ownership *starts* releasing from the affected groups.
    is_claiming = ip.owner_port_id is None and fp.owner_port_id is not None
    is_releasing = ip.owner_port_id is not None and fp.owner_port_id is None

    if not gating:
        # No relevant relay transitions — this pack changes when the output
        # relay flips (anchor-group packs).
        out_id = _output_relay_id(candidate_port)
        if is_claiming:
            return fp.owner_port_id if out_id in applied else ip.owner_port_id
        if is_releasing:
            return fp.owner_port_id if out_id in applied else ip.owner_port_id
        return fp.owner_port_id

    if is_claiming:
        # All gating relays must be applied (and closed) to connect this pack
        return fp.owner_port_id if gating.issubset(applied) else ip.owner_port_id
    if is_releasing:
        # As soon as ANY gating relay applies (opens), this pack disconnects
        return fp.owner_port_id if gating & applied else ip.owner_port_id
    return fp.owner_port_id


# ---------------------------------------------------------------------------
# Step 6 — Description builder
# ---------------------------------------------------------------------------

_RELAY_ID_RE = re.compile(r"^M(\d+)\.([OR])(\d+)$")


def _display_relay_id(relay_id: str) -> str:
    """Render an internal relay_id (M{n}.O{k} / M{n}.R{k}) for human-facing
    step descriptions; display only, does not mutate the stored relay_id."""
    m = _RELAY_ID_RE.match(relay_id)
    if not m:
        return relay_id  # unknown format → pass through unchanged
    bd, kind, k = m.group(1), m.group(2), m.group(3)
    label = "OUTPUT" if kind == "O" else "RELAY"
    return f"MCU{bd}.{label}{k}"


def _describe(
    flip: _RelayFlip,
    snap: VisualSnapshot,
    phase: str,
) -> str:
    rid = _display_relay_id(flip.relay_id)
    pid = flip.port
    if pid <= 0:
        action = "Close" if flip.to_state == "Closed" else "Open"
        return f"{action} {rid}"

    car = next((c for c in snap.cars if c.port_id == pid), None)
    alloc = car.allocated_kw if car else 0

    if phase == _Phase.ARRIVAL:
        if flip.kind == "output":
            return f"Close {rid} (Port {pid} engaged at {alloc} kW)"
        return f"Close {rid} (Port {pid} engaging)"
    if phase == _Phase.INCREASE:
        return f"Close {rid} (Port {pid} expanding to {alloc} kW)"
    if phase == _Phase.DEPARTURE:
        if flip.kind == "output":
            return f"Open {rid} (Port {pid} disengaged)"
        return f"Open {rid} (Port {pid} releasing)"
    if phase == _Phase.DECREASE:
        return f"Open {rid} (Port {pid} releasing to {alloc} kW)"
    action = "Close" if flip.to_state == "Closed" else "Open"
    return f"{action} {rid}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def plan_transition(
    system: SystemConfig,
    car_ports: List[CarPortInput],
    initial_state: VisualSnapshot,
    final_state: VisualSnapshot,
) -> List[ControlStep]:
    """Walk present→target via progressive ``max_required``, emitting one
    ``ControlStep`` per relay state change between consecutive settled
    snapshots.

    ``initial_state`` / ``final_state`` are kept for signature compatibility
    but unused — every emitted snapshot comes from ``WebSessionEngine.create()``
    so SPEC §11 ordering is free.
    """
    raw = await _generate_progressive_snapshots(system, car_ports)
    deduped = _dedup_snapshots(raw)
    if len(deduped) < 2:
        return []

    ports_by_id = {p.port_id: p for p in car_ports}
    steps: List[ControlStep] = []

    for i in range(1, len(deduped)):
        prev_snap = deduped[i - 1][1]
        curr_snap = deduped[i][1]

        # Attribute every diff to its owning port, then sort by that port's
        # priority so FR-16 ordering survives when multiple ports change at
        # the same demand level (otherwise relays are emitted in mcu_idx /
        # lexical order regardless of priority).
        attributed: List[Tuple[int, str, RelaySnapshot, RelaySnapshot, int]] = []
        for ir, fr in _relay_diff(prev_snap, curr_snap):
            port = _attribute_flip(
                ir, fr, prev_snap, curr_snap, ports_by_id, system
            )
            prio = (
                _prio_key(ports_by_id[port]) if port in ports_by_id else 10**9
            )
            attributed.append((prio, fr.id, ir, fr, port))
        attributed.sort(key=lambda x: (x[0], x[1]))

        for _, _, ir, fr, port in attributed:
            flip = _RelayFlip(
                relay_id=fr.id,
                from_state=ir.state,
                to_state=fr.state,
                kind=fr.kind,
                owner_port_id=fr.owner_port_id,
                rec_bd_id=fr.rec_bd_id,
                port=port,
            )
            port_phase = _Phase.NO_CHANGE
            if port in ports_by_id:
                port_phase = _phase_of(ports_by_id[port])
            desc = _describe(flip, curr_snap, port_phase)
            steps.append(
                ControlStep(
                    step_index=len(steps), description=desc, snapshot=curr_snap
                )
            )

    return steps
