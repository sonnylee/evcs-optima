"""Diff-based control-step planner (Phase 3, FR-14 / FR-15).

Walks each Car Port's effective ``max_required`` from ``present`` toward
``target`` in 25 kW increments, recomputes the visual snapshot each tick via
``state_calculation_service.compute_snapshot``, and emits one ``ControlStep``
per macro tick.

SPEC §11 hardware ordering is enforced by post-processing snapshots:

* **Arrival** (``present == 0``, ``target > 0``): the Output relay is held
  Open and the Car shown Inactive while the port's allocation is below
  ``MIN_ENGAGE_KW`` (125 kW). When allocation crosses 125 kW for the first
  time, the macro tick is split — Step A shows the pack already claimed but
  Output still Open; Step B closes the Output. After that, the port is
  permanently unlocked.
* **Departure** (``target == 0``, ``present > 0``): when the port's
  ``max_required`` reaches 0 the macro tick is split — Step A shows the last
  pack released and inter-group relays already open with Output still
  Closed; Step B opens the Output.
"""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

from app.constants import (
    CAR_COLOR_ACTIVE,
    CAR_COLOR_INACTIVE,
    RELAY_COLOR_CLOSED,
    RELAY_COLOR_OPEN,
    STEP_KW,
)
from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.control_step import ControlStep
from app.schemas.snapshot import VisualSnapshot
from app.services.config_service import home_rec_bd_for_port
from app.services.state_calculation_service import compute_snapshot


MIN_ENGAGE_KW = 125  # SPEC §11: Output relay may close only at or above this


# ---------------------------------------------------------------------------
# Schedule
# ---------------------------------------------------------------------------

def _prio_key(cp: CarPortInput) -> int:
    return cp.priority if cp.priority is not None else 10**9


def _build_schedule(car_ports: List[CarPortInput]) -> List[Tuple[int, int]]:
    """Return ``(port_id, new_max_required)`` ticks in execution order.

    Phase A — full departures (target == 0, present > 0), priority asc.
    Phase B — partial releases (0 < target < present), reverse priority.
    Phase C — gains + arrivals (target > present), priority asc.
    """

    departures = sorted(
        [p for p in car_ports if p.target == 0 and p.present > 0],
        key=lambda p: (_prio_key(p), p.port_id),
    )
    releases = sorted(
        [p for p in car_ports if 0 < p.target < p.present],
        key=lambda p: (-_prio_key(p), p.port_id),
    )
    gains_and_arrivals = sorted(
        [p for p in car_ports if p.target > p.present],
        key=lambda p: (_prio_key(p), p.port_id),
    )

    schedule: List[Tuple[int, int]] = []

    for p in departures + releases:
        v = p.present - STEP_KW
        while v >= p.target:
            schedule.append((p.port_id, v))
            v -= STEP_KW

    for p in gains_and_arrivals:
        v = p.present + STEP_KW
        while v <= p.target:
            schedule.append((p.port_id, v))
            v += STEP_KW

    return schedule


# ---------------------------------------------------------------------------
# Snapshot overrides (SPEC §11)
# ---------------------------------------------------------------------------

def _allocated_for(snap: VisualSnapshot, port_id: int) -> int:
    for c in snap.cars:
        if c.port_id == port_id:
            return c.allocated_kw
    return 0


def _apply_arrival_override(
    snap: VisualSnapshot, pre_engage_locked: Set[int]
) -> VisualSnapshot:
    """Force Output Open + Car Inactive for ports still pre-engaged (<125 kW)."""

    if not pre_engage_locked:
        return snap

    new_relays = [
        r.model_copy(update={"state": "Open", "color": RELAY_COLOR_OPEN})
        if r.kind == "output" and r.owner_port_id in pre_engage_locked
        else r
        for r in snap.relays
    ]
    new_cars = [
        c.model_copy(update={"status": "Inactive", "color": CAR_COLOR_INACTIVE})
        if c.port_id in pre_engage_locked and c.allocated_kw > 0
        else c
        for c in snap.cars
    ]
    return snap.model_copy(update={"relays": new_relays, "cars": new_cars})


def _force_output_closed(snap: VisualSnapshot, port_id: int) -> VisualSnapshot:
    """Force Output Closed + Car Active for one port (used at pre-disengagement)."""

    new_relays = [
        r.model_copy(update={"state": "Closed", "color": RELAY_COLOR_CLOSED})
        if r.kind == "output" and r.owner_port_id == port_id
        else r
        for r in snap.relays
    ]
    new_cars = [
        c.model_copy(update={"status": "Active", "color": CAR_COLOR_ACTIVE})
        if c.port_id == port_id
        else c
        for c in snap.cars
    ]
    return snap.model_copy(update={"relays": new_relays, "cars": new_cars})


# ---------------------------------------------------------------------------
# Description builder
# ---------------------------------------------------------------------------

def _diff_relay_changes(prev: VisualSnapshot, curr: VisualSnapshot) -> List[Tuple[str, str]]:
    prev_states = {r.id: r.state for r in prev.relays}
    out: List[Tuple[str, str]] = []
    for r in curr.relays:
        if prev_states.get(r.id) != r.state:
            out.append((r.id, r.state))
    return out


def _diff_pack_changes(
    prev: VisualSnapshot, curr: VisualSnapshot
) -> List[Tuple[int, int, "int | None", "int | None"]]:
    prev_owners = {(p.rec_bd_id, p.pack_index): p.owner_port_id for p in prev.packs}
    out: List[Tuple[int, int, "int | None", "int | None"]] = []
    for p in curr.packs:
        po = prev_owners.get((p.rec_bd_id, p.pack_index))
        if po != p.owner_port_id:
            out.append((p.rec_bd_id, p.pack_index, po, p.owner_port_id))
    return out


def _describe_tick(
    port_id: int,
    prev_mr: int,
    new_mr: int,
    prev: VisualSnapshot,
    curr: VisualSnapshot,
) -> str:
    relay_diff = _diff_relay_changes(prev, curr)
    direction = "increase" if new_mr > prev_mr else "decrease"
    base = f"Port {port_id} {direction} to {new_mr} kW"
    if not relay_diff:
        return base
    parts = [
        f"{'close' if state == 'Closed' else 'open'} {rid}" for rid, state in relay_diff
    ]
    return f"{base} ({', '.join(parts)})"


def _output_relay_id(port_id: int) -> str:
    home = home_rec_bd_for_port(port_id)
    local_idx = (port_id - 1) % 2 + 1
    return f"M{home}.O{local_idx}"


# ---------------------------------------------------------------------------
# Main planner
# ---------------------------------------------------------------------------

def plan_transition(
    system: SystemConfig,
    car_ports: List[CarPortInput],
    initial_state: VisualSnapshot,
) -> List[ControlStep]:
    """Walk Present → Target and emit one ControlStep per atomic transition tick."""

    schedule = _build_schedule(car_ports)

    arrival_ports: Set[int] = {
        p.port_id for p in car_ports if p.present == 0 and p.target > 0
    }
    departure_ports: Set[int] = {
        p.port_id for p in car_ports if p.target == 0 and p.present > 0
    }

    pre_engage_locked: Set[int] = set(arrival_ports)
    current_mr: Dict[int, int] = {p.port_id: p.present for p in car_ports}

    prev = _apply_arrival_override(initial_state, pre_engage_locked)
    steps: List[ControlStep] = []

    def emit(snap: VisualSnapshot, description: str) -> None:
        nonlocal prev
        if snap == prev:
            return
        steps.append(
            ControlStep(step_index=len(steps), description=description, snapshot=snap)
        )
        prev = snap

    for port_id, new_mr in schedule:
        prev_mr = current_mr[port_id]
        current_mr[port_id] = new_mr

        ports_now = [
            p.model_copy(update={"max_required": current_mr[p.port_id]})
            for p in car_ports
        ]
        raw = compute_snapshot(system, ports_now)

        crosses_engagement = (
            port_id in pre_engage_locked
            and _allocated_for(raw, port_id) >= MIN_ENGAGE_KW
        )
        crosses_disengagement = port_id in departure_ports and new_mr == 0

        if crosses_engagement:
            allocated = _allocated_for(raw, port_id)
            # Step A — pack claimed, allocation now ≥125 kW, but Output still Open.
            cooked_a = _apply_arrival_override(raw, pre_engage_locked)
            emit(
                cooked_a,
                f"Port {port_id} reaches {allocated} kW (≥{MIN_ENGAGE_KW} kW, ready to engage)",
            )
            # Step B — release lock, Output closes.
            pre_engage_locked.discard(port_id)
            cooked_b = _apply_arrival_override(raw, pre_engage_locked)
            emit(
                cooked_b,
                f"Close {_output_relay_id(port_id)} (Port {port_id} engaged at {allocated} kW)",
            )
        elif crosses_disengagement:
            # Step A — final pack released, inter-group relays open, but Output held Closed.
            cooked_a = _force_output_closed(
                _apply_arrival_override(raw, pre_engage_locked), port_id
            )
            emit(
                cooked_a,
                f"Port {port_id} released (inter-group relays opened, Output held Closed)",
            )
            # Step B — Output opens (natural).
            cooked_b = _apply_arrival_override(raw, pre_engage_locked)
            emit(
                cooked_b,
                f"Open {_output_relay_id(port_id)} (Port {port_id} disengaged)",
            )
        else:
            cooked = _apply_arrival_override(raw, pre_engage_locked)
            emit(cooked, _describe_tick(port_id, prev_mr, new_mr, prev, cooked))

    return steps
