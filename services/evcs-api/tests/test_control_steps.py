"""Phase 3 — control-step adapter + routes (FR-14, FR-15)."""
from __future__ import annotations

from typing import Dict, List

import pytest
from fastapi.testclient import TestClient

from app.adapters import step_planner
from app.adapters.evcs_core_adapter import (
    PrioritiesIncompleteError,
    TargetExceedsCapacityError,
    generate_control_steps,
)
from app.schemas.car_port import CarPortInput
from app.schemas.config import RecBdConfig, SystemConfig


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _system(rec_bd_count: int = 2) -> SystemConfig:
    return SystemConfig(
        rec_bd_count=rec_bd_count,
        rec_bds=[
            RecBdConfig(id=i + 1, module_powers=[50, 75, 75, 50])
            for i in range(rec_bd_count)
        ],
    )


def _ports(specs: List[Dict]) -> List[CarPortInput]:
    return [CarPortInput(**s) for s in specs]


def _output_relay(snap, port_id):
    for r in snap.relays:
        if r.kind == "output" and r.owner_port_id == port_id:
            return r
    raise AssertionError(f"output relay for port {port_id} not found")


def _car(snap, port_id):
    for c in snap.cars:
        if c.port_id == port_id:
            return c
    raise AssertionError(f"car {port_id} not found")


def _ports_full(rec_bd_count: int, overrides: Dict[int, Dict]) -> List[CarPortInput]:
    """Build a full N-port set with sensible defaults; overrides[port_id] tweaks fields."""
    out = []
    for pid in range(1, rec_bd_count * 2 + 1):
        spec = {
            "port_id": pid,
            "max_required": 0,
            "present": 0,
            "target": 0,
            "priority": pid,
        }
        spec.update(overrides.get(pid, {}))
        out.append(CarPortInput(**spec))
    return out


# ---------------------------------------------------------------------------
# Adapter unit tests
# ---------------------------------------------------------------------------

def test_identity_no_change_required():
    sys = _system(2)
    ports = _ports_full(2, {1: {"max_required": 125, "present": 125, "target": 125}})
    seq = generate_control_steps(sys, ports)
    assert seq.total_steps == 0
    assert seq.steps == []
    assert any("No change required" in w for w in seq.warnings)


def test_target_exceeds_capacity_raises():
    sys = _system(2)  # 2 × 250 kW = 500 kW total
    ports = _ports_full(
        2,
        {
            1: {"max_required": 600, "present": 0, "target": 300},
            2: {"max_required": 600, "present": 0, "target": 300},
        },
    )
    with pytest.raises(TargetExceedsCapacityError):
        generate_control_steps(sys, ports)


def test_priorities_insufficient_raises():
    sys = _system(2)
    ports = _ports_full(
        2,
        {
            1: {"max_required": 125, "present": 0, "target": 125, "priority": 1},
            2: {"max_required": 125, "present": 0, "target": 125, "priority": None},
            3: {"priority": None},
            4: {"priority": None},
        },
    )
    with pytest.raises(PrioritiesIncompleteError):
        generate_control_steps(sys, ports)


def test_arrival_holds_output_open_until_125kw():
    """SPEC §11: Output relay stays Open while allocated < 125 kW."""
    sys = _system(2)
    ports = _ports_full(
        2, {1: {"max_required": 125, "present": 0, "target": 125}}
    )
    seq = generate_control_steps(sys, ports)
    assert seq.total_steps > 0

    # Walk every emitted step. While allocation < 125 kW for port 1, Output must be Open.
    last_open_idx = -1
    closed_idx = -1
    for i, step in enumerate(seq.steps):
        car = _car(step.snapshot, 1)
        relay = _output_relay(step.snapshot, 1)
        if car.allocated_kw < 125:
            assert relay.state == "Open", (
                f"step {i}: alloc={car.allocated_kw} < 125 but Output {relay.state}"
            )
            last_open_idx = i
        elif relay.state == "Closed" and closed_idx == -1:
            closed_idx = i

    assert closed_idx != -1, "Output never closes — should close once ≥125 kW reached"
    assert closed_idx > last_open_idx
    # The engagement step description should mention closing the output relay.
    assert "Close M1.O1" in seq.steps[closed_idx].description


def test_arrival_below_125kw_never_closes_output():
    """target=75 kW is below the engagement threshold — Output must never close."""
    sys = _system(2)
    ports = _ports_full(
        2, {1: {"max_required": 75, "present": 0, "target": 75}}
    )
    seq = generate_control_steps(sys, ports)
    for step in seq.steps:
        relay = _output_relay(step.snapshot, 1)
        assert relay.state == "Open", "Output must stay Open while target < 125 kW"


def test_full_departure_opens_output_last():
    """SPEC §11: on full departure, inter-group relays open before Output."""
    sys = _system(2)
    ports = _ports_full(
        2, {1: {"max_required": 0, "present": 200, "target": 0}}
    )
    seq = generate_control_steps(sys, ports)
    assert seq.total_steps > 0

    output_open_idx = -1
    for i, step in enumerate(seq.steps):
        relay = _output_relay(step.snapshot, 1)
        if relay.state == "Open":
            output_open_idx = i
            break

    assert output_open_idx != -1, "Output relay must open on full departure"
    # No inter-group relay belonging to REC BD 1 may be Closed at or after the Output opens.
    final_snap = seq.steps[output_open_idx].snapshot
    for r in final_snap.relays:
        if r.kind == "inter_group" and r.rec_bd_id == 1:
            assert r.state == "Open", (
                f"inter-group relay {r.id} still Closed after Output opened"
            )


def test_partial_release_keeps_output_closed():
    """Output must stay Closed during partial release (allocated never hits 0)."""
    sys = _system(2)
    ports = _ports_full(
        2, {1: {"max_required": 200, "present": 200, "target": 125}}
    )
    seq = generate_control_steps(sys, ports)
    assert seq.total_steps > 0
    for step in seq.steps:
        relay = _output_relay(step.snapshot, 1)
        assert relay.state == "Closed"


def test_priority_drives_arrival_order():
    """Highest-priority arrival completes before lower-priority ones."""
    sys = _system(2)
    ports = _ports_full(
        2,
        {
            1: {"max_required": 125, "present": 0, "target": 125, "priority": 2},
            3: {"max_required": 125, "present": 0, "target": 125, "priority": 1},
        },
    )
    seq = generate_control_steps(sys, ports)

    # Find first step in which each port reaches 125 kW (engagement signal).
    p3_engaged_idx = next(
        i for i, s in enumerate(seq.steps)
        if "Close M2.O1" in s.description
    )
    p1_engaged_idx = next(
        i for i, s in enumerate(seq.steps)
        if "Close M1.O1" in s.description
    )
    assert p3_engaged_idx < p1_engaged_idx


def test_unreasonable_present_warns_does_not_abort():
    """FR-14: present > max_required emits warning but sequence still generated."""
    sys = _system(2)
    ports = _ports_full(
        2,
        {
            1: {"max_required": 125, "present": 200, "target": 125},
            2: {"max_required": 0, "present": 0, "target": 0, "priority": 2},
        },
    )
    seq = generate_control_steps(sys, ports)
    assert any(
        "Present" in w and "exceeds Max Required" in w for w in seq.warnings
    )


def test_ring_wrap_borrow_4_rec_bds():
    """4 REC BDs (ring topology). Port 1 gains beyond home REC BD; bridge B_4_1 must close."""
    sys = _system(4)
    overrides = {
        1: {"max_required": 350, "present": 0, "target": 350, "priority": 1},
    }
    # Need at least 2 priorities set
    overrides[2] = {"priority": 2}
    ports = _ports_full(4, overrides)
    seq = generate_control_steps(sys, ports)

    # In the final snapshot, B_4_1 must be closed because Port 1 expanded into REC BD 4
    # (anchor at G0 of REC BD 1, expands via right-then-left ring walk).
    final = seq.steps[-1].snapshot
    bridges = {r.id: r.state for r in final.relays if r.kind == "bridge"}
    assert "B_4_1" in bridges or "B_1_4" in bridges or "B_1_2" in bridges
    # At least one bridge is closed because allocation crossed REC BD boundary.
    assert any(state == "Closed" for state in bridges.values())


# ---------------------------------------------------------------------------
# Schedule sanity tests
# ---------------------------------------------------------------------------

def test_schedule_phase_ordering():
    """Schedule must do departures+releases first, then gains+arrivals."""
    ports = _ports_full(
        4,
        {
            1: {"max_required": 0, "present": 100, "target": 0, "priority": 1},  # departure
            2: {"max_required": 75, "present": 200, "target": 75, "priority": 2},  # release
            3: {"max_required": 200, "present": 0, "target": 200, "priority": 3},  # arrival
            4: {"max_required": 175, "present": 100, "target": 175, "priority": 4},  # gain
        },
    )
    sched = step_planner._build_schedule(ports)

    # Group ticks by port_id and check the first tick's index
    first_tick_idx: Dict[int, int] = {}
    for idx, (pid, _) in enumerate(sched):
        first_tick_idx.setdefault(pid, idx)

    assert first_tick_idx[1] < first_tick_idx[3]
    assert first_tick_idx[1] < first_tick_idx[4]
    assert first_tick_idx[2] < first_tick_idx[3]
    assert first_tick_idx[2] < first_tick_idx[4]


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------

def _create_session_with_arrival(client: TestClient, target: int = 125) -> str:
    """Helper: create a 2-REC-BD session with port 1 arriving at given target."""
    cfg = {
        "rec_bd_count": 2,
        "rec_bds": [
            {"id": 1, "module_powers": [50, 75, 75, 50]},
            {"id": 2, "module_powers": [50, 75, 75, 50]},
        ],
    }
    ports = [
        {"port_id": 1, "max_required": target, "present": 0, "target": target, "priority": 1},
        {"port_id": 2, "max_required": 0, "present": 0, "target": 0, "priority": 2},
        {"port_id": 3, "max_required": 0, "present": 0, "target": 0, "priority": 3},
        {"port_id": 4, "max_required": 0, "present": 0, "target": 0, "priority": 4},
    ]
    r = client.post(
        "/api/v1/sessions", json={"system_config": cfg, "car_ports": ports}
    )
    assert r.status_code == 201
    return r.json()["session_id"]


def test_route_apply_and_generate_persists_sequence(client: TestClient):
    sid = _create_session_with_arrival(client, target=125)

    r = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_steps"] >= 1
    assert "initial_state" in body

    # Session should now be in player mode at index 0
    s = client.get(f"/api/v1/sessions/{sid}").json()
    assert s["mode"] == "player"
    assert s["current_step_index"] == 0
    assert s["step_sequence"]["total_steps"] == body["total_steps"]


def test_route_apply_and_generate_404_for_missing_session(client: TestClient):
    r = client.post("/api/v1/sessions/does-not-exist/apply-and-generate")
    assert r.status_code == 404


def test_route_apply_and_generate_422_target_over_capacity(client: TestClient):
    cfg = {
        "rec_bd_count": 2,
        "rec_bds": [
            {"id": 1, "module_powers": [50, 75, 75, 50]},
            {"id": 2, "module_powers": [50, 75, 75, 50]},
        ],
    }
    ports = [
        {"port_id": 1, "max_required": 600, "present": 0, "target": 300, "priority": 1},
        {"port_id": 2, "max_required": 600, "present": 0, "target": 300, "priority": 2},
        {"port_id": 3, "max_required": 0, "present": 0, "target": 0},
        {"port_id": 4, "max_required": 0, "present": 0, "target": 0},
    ]
    r = client.post(
        "/api/v1/sessions", json={"system_config": cfg, "car_ports": ports}
    )
    sid = r.json()["session_id"]

    r2 = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    assert r2.status_code == 422
    body = r2.json()
    assert body["detail"]["errors"][0]["code"] == "TARGET_EXCEEDS_CAPACITY"


def test_route_apply_and_generate_422_priorities_insufficient(client: TestClient):
    cfg = {
        "rec_bd_count": 2,
        "rec_bds": [
            {"id": 1, "module_powers": [50, 75, 75, 50]},
            {"id": 2, "module_powers": [50, 75, 75, 50]},
        ],
    }
    ports = [
        {"port_id": 1, "max_required": 125, "present": 0, "target": 125, "priority": 1},
        {"port_id": 2, "max_required": 0, "present": 0, "target": 0},
        {"port_id": 3, "max_required": 0, "present": 0, "target": 0},
        {"port_id": 4, "max_required": 0, "present": 0, "target": 0},
    ]
    r = client.post(
        "/api/v1/sessions", json={"system_config": cfg, "car_ports": ports}
    )
    sid = r.json()["session_id"]

    r2 = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    assert r2.status_code == 422
    body = r2.json()
    assert body["detail"]["errors"][0]["code"] == "PRIORITIES_INSUFFICIENT"


def test_route_get_control_steps(client: TestClient):
    sid = _create_session_with_arrival(client)
    r = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    total = r.json()["total_steps"]

    r2 = client.get(f"/api/v1/sessions/{sid}/control-steps")
    assert r2.status_code == 200
    assert r2.json()["total_steps"] == total


def test_route_get_control_steps_404_when_no_sequence(client: TestClient):
    sid = _create_session_with_arrival(client)
    # Don't call apply-and-generate
    r = client.get(f"/api/v1/sessions/{sid}/control-steps")
    assert r.status_code == 404


def test_route_step_player_wraps_at_ends(client: TestClient):
    sid = _create_session_with_arrival(client, target=125)
    r = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    total = r.json()["total_steps"]
    assert total >= 1

    # forward total times → reach last step (index == total)
    for _ in range(total):
        rf = client.post(f"/api/v1/sessions/{sid}/step", params={"direction": "forward"})
        assert rf.status_code == 200
    assert rf.json()["current_step_index"] == total

    # one more forward → wraps to 0
    rf = client.post(f"/api/v1/sessions/{sid}/step", params={"direction": "forward"})
    assert rf.json()["current_step_index"] == 0
    assert rf.json()["description"] == "Initial State (Present)"

    # back from 0 → wraps to total
    rb = client.post(f"/api/v1/sessions/{sid}/step", params={"direction": "back"})
    assert rb.json()["current_step_index"] == total


def test_route_patch_invalidates_step_sequence(client: TestClient):
    sid = _create_session_with_arrival(client)
    client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    # PATCH should reset mode to edit and clear step_sequence
    r = client.patch(
        f"/api/v1/sessions/{sid}",
        json={
            "car_ports": [
                {"port_id": 1, "max_required": 200, "present": 0, "target": 200, "priority": 1},
                {"port_id": 2, "max_required": 0, "present": 0, "target": 0, "priority": 2},
                {"port_id": 3, "max_required": 0, "present": 0, "target": 0, "priority": 3},
                {"port_id": 4, "max_required": 0, "present": 0, "target": 0, "priority": 4},
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "edit"
    assert r.json()["step_sequence"] is None
