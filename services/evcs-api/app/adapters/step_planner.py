"""Rebuild + diff control-step planner (Phase 3, Step F14.1 — FR-14 / FR-15).

The caller (``evcs_core_adapter.generate_control_steps``) supplies two
already-converged ``VisualSnapshot`` instances — ``initial_state`` (built with
``max_required = present``) and ``final_state`` (built with ``max_required =
target``). This module's job is purely combinatorial: enumerate the relays
whose state differs between the two snapshots, schedule those flips into a
SPEC §11-compliant order, and emit one ``ControlStep`` per atomic flip with
an interpolated mid-state snapshot.

Algorithm (5 steps):

1. **Per-port classification** — arrivals / departures / increases /
   decreases / no_change.
2. **Relay diff** — pair ``initial.relays`` with ``final.relays`` by id; keep
   only those with different ``state``.
3. **Phase sort (cross-port)** — Phase A: full departures (priority asc);
   Phase B: partial decreases (priority desc — low priority releases first);
   Phase C: arrivals + increases (priority asc).
4. **SPEC §11 sort (within-port)** — inter-group / bridge before output on
   arrival; inter-group / bridge before output on departure; release-side
   walks high→low, engage-side walks low→high.
5. **Snapshot stitching** — accumulate applied flips and reconstruct each
   intermediate snapshot by blending ``initial_state`` and ``final_state``
   field-by-field.

References: ``docs/SPEC-WEB-API.md`` §3.3, ``docs/SPEC.md`` §11.
"""
from __future__ import annotations

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

    Output relay: owner_port_id is on the relay itself.
    Inter-group / bridge: look at packs adjacent to the relay; favour the
    port that owns them in final (closing) or initial (opening). On
    "leaving meets arriving" tie, prefer the departing port (release-then-
    engage).
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
# Step 3 + 4 — Schedule the flips
# ---------------------------------------------------------------------------

def _schedule_flips(
    flips: List[_RelayFlip],
    car_ports: List[CarPortInput],
) -> List[_RelayFlip]:
    """Phase A → B → C, with SPEC §11 ordering inside each port's subset."""
    ports_by_id = {p.port_id: p for p in car_ports}

    departures = [p for p in car_ports if _phase_of(p) == _Phase.DEPARTURE]
    decreases = [p for p in car_ports if _phase_of(p) == _Phase.DECREASE]
    arrivals = [p for p in car_ports if _phase_of(p) == _Phase.ARRIVAL]
    increases = [p for p in car_ports if _phase_of(p) == _Phase.INCREASE]

    departures.sort(key=lambda p: (_prio_key(p), p.port_id))
    decreases.sort(key=lambda p: (-_prio_key(p), p.port_id))
    arrivals.sort(key=lambda p: (_prio_key(p), p.port_id))
    increases.sort(key=lambda p: (_prio_key(p), p.port_id))

    flips_by_port: Dict[int, List[_RelayFlip]] = {}
    for f in flips:
        flips_by_port.setdefault(f.port, []).append(f)

    result: List[_RelayFlip] = []
    seen_port_phases: Set[Tuple[int, str]] = set()

    def _emit_port(port: CarPortInput, phase: str) -> None:
        key = (port.port_id, phase)
        if key in seen_port_phases:
            return
        seen_port_phases.add(key)
        sub = flips_by_port.get(port.port_id, [])
        result.extend(_order_within_port(sub, phase))

    # Phase A — departures
    for p in departures:
        _emit_port(p, _Phase.DEPARTURE)
    # Phase B — decreases
    for p in decreases:
        _emit_port(p, _Phase.DECREASE)
    # Phase C — arrivals + increases (priority asc, mixed)
    pc = sorted(arrivals + increases, key=lambda p: (_prio_key(p), p.port_id))
    for p in pc:
        phase = _phase_of(p)
        _emit_port(p, phase)

    # Catch-all: any unattributed flips (port=0) go at the end, sorted by id
    leftovers = sorted(
        [f for f in flips if f.port == 0 and f not in result],
        key=lambda f: f.relay_id,
    )
    result.extend(leftovers)
    return result


def _order_within_port(flips: List[_RelayFlip], phase: str) -> List[_RelayFlip]:
    """SPEC §11 order: inter-group / bridge before output on engage and disengage.

    Within inter-group / bridge:
      - Engage (close): walk anchor-outward (= rec_bd_id asc, relay_id asc)
      - Disengage (open): walk outward-inward (= rec_bd_id desc, relay_id desc)
    """
    if not flips:
        return []
    output_flips = [f for f in flips if f.kind == "output"]
    other = [f for f in flips if f.kind != "output"]

    if phase in (_Phase.ARRIVAL, _Phase.INCREASE):
        # Engage: bridges/inter-group first (low → high), then output
        other_sorted = sorted(other, key=_engage_key)
        return other_sorted + output_flips
    if phase in (_Phase.DEPARTURE, _Phase.DECREASE):
        # Disengage: bridges/inter-group first (high → low), then output
        other_sorted = sorted(other, key=_disengage_key)
        return other_sorted + output_flips
    return flips


def _engage_key(f: _RelayFlip) -> Tuple[int, int, str]:
    # Inner-out from anchor: prefer same REC BD inter-group ascending; bridges last
    kind_order = {"inter_group": 0, "bridge": 1}
    bd = f.rec_bd_id if f.rec_bd_id is not None else 99
    return (kind_order.get(f.kind, 2), bd, f.relay_id)


def _disengage_key(f: _RelayFlip) -> Tuple[int, int, str]:
    # Outer-in to anchor: bridges first, then inter-group descending
    kind_order = {"bridge": 0, "inter_group": 1}
    bd = -f.rec_bd_id if f.rec_bd_id is not None else 99
    return (kind_order.get(f.kind, 2), bd, _negate_relay_id(f.relay_id))


def _negate_relay_id(rid: str) -> str:
    """Reverse-sort helper — turn 'M1.R3' into a string that sorts before 'M1.R2'."""
    return "".join(chr(255 - ord(c)) for c in rid)


# ---------------------------------------------------------------------------
# Phase ordering (compat helper)
# ---------------------------------------------------------------------------

def _build_schedule(car_ports: List[CarPortInput]) -> List[Tuple[int, int]]:
    """Return ``(port_id, 0)`` tuples in Phase A → B → C order.

    Kept as a small introspection helper (and consumed by
    ``test_schedule_phase_ordering``) — the rebuild + diff strategy no
    longer walks ticks per 25 kW.
    """
    departures = sorted(
        [p for p in car_ports if _phase_of(p) == _Phase.DEPARTURE],
        key=lambda p: (_prio_key(p), p.port_id),
    )
    decreases = sorted(
        [p for p in car_ports if _phase_of(p) == _Phase.DECREASE],
        key=lambda p: (-_prio_key(p), p.port_id),
    )
    arrivals_increases = sorted(
        [p for p in car_ports if _phase_of(p) in (_Phase.ARRIVAL, _Phase.INCREASE)],
        key=lambda p: (_prio_key(p), p.port_id),
    )
    return [(p.port_id, 0) for p in (departures + decreases + arrivals_increases)]


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

    Relays: applied flips → final value; otherwise → initial.
    Packs: per-pack heuristic — switch to final ownership only after the
        relay flips that connect this pack's group to its (final or initial)
        owner's anchor have all been applied.
    Cars: derived from packs + current output relay state.
    rec_bds: derived from packs.
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

    Heuristic: identify the candidate port (final owner if claiming, initial
    owner if releasing). Find the relay flip(s) that "gate" this pack. If
    every gating flip is applied → use final owner; else → use initial.
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

def _describe(
    flip: _RelayFlip,
    snap: VisualSnapshot,
    phase: str,
) -> str:
    pid = flip.port
    if pid <= 0:
        action = "Close" if flip.to_state == "Closed" else "Open"
        return f"{action} {flip.relay_id}"

    car = next((c for c in snap.cars if c.port_id == pid), None)
    alloc = car.allocated_kw if car else 0

    if phase == _Phase.ARRIVAL:
        if flip.kind == "output":
            return f"Close {flip.relay_id} (Port {pid} engaged at {alloc} kW)"
        return f"Close {flip.relay_id} (Port {pid} engaging)"
    if phase == _Phase.INCREASE:
        return f"Close {flip.relay_id} (Port {pid} expanding to {alloc} kW)"
    if phase == _Phase.DEPARTURE:
        if flip.kind == "output":
            return f"Open {flip.relay_id} (Port {pid} disengaged)"
        return f"Open {flip.relay_id} (Port {pid} releasing)"
    if phase == _Phase.DECREASE:
        return f"Open {flip.relay_id} (Port {pid} releasing to {alloc} kW)"
    action = "Close" if flip.to_state == "Closed" else "Open"
    return f"{action} {flip.relay_id}"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def plan_transition(
    system: SystemConfig,
    car_ports: List[CarPortInput],
    initial_state: VisualSnapshot,
    final_state: VisualSnapshot,
) -> List[ControlStep]:
    """Diff ``initial_state`` and ``final_state`` and emit one
    ``ControlStep`` per atomic relay flip, in SPEC §11 order.
    """
    ports_by_id = {p.port_id: p for p in car_ports}

    # 1+2 — Diff and attribute
    raw_diffs = _relay_diff(initial_state, final_state)
    flips: List[_RelayFlip] = []
    for ir, fr in raw_diffs:
        port = _attribute_flip(ir, fr, initial_state, final_state, ports_by_id, system)
        flips.append(
            _RelayFlip(
                relay_id=fr.id,
                from_state=ir.state,
                to_state=fr.state,
                kind=fr.kind,
                owner_port_id=fr.owner_port_id,
                rec_bd_id=fr.rec_bd_id,
                port=port,
            )
        )

    # 3+4 — Schedule
    ordered = _schedule_flips(flips, car_ports)

    # 5 — Stitch + emit
    applied: Set[str] = set()
    steps: List[ControlStep] = []
    for f in ordered:
        applied.add(f.relay_id)
        snap = _stitch_snapshot(
            system, car_ports, initial_state, final_state, applied, ordered
        )
        port_phase = _Phase.NO_CHANGE
        if f.port in ports_by_id:
            port_phase = _phase_of(ports_by_id[f.port])
        desc = _describe(f, snap, port_phase)
        steps.append(
            ControlStep(step_index=len(steps), description=desc, snapshot=snap)
        )

    return steps
