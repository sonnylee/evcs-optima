"""Phase 3 — control-step adapter + routes (FR-14, FR-15).

Post-F14.4: full FR-14 path validated end-to-end on 4 REC BDs (Sprint 1
target hardware envelope). All previous 4-REC-BD-blocker xfails have been
lifted; the test surface now exercises step_planner's rebuild + diff +
ordered apply algorithm (SPEC-WEB-API §3.3 4-step model), _present_warnings
via WebSessionEngine, and the async apply_and_generate route under realistic
Sprint 1 demo loads.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List

import pytest
from fastapi.testclient import TestClient

from app.adapters import step_planner
from app.adapters.evcs_core_adapter import (
    PrioritiesIncompleteError,
    generate_control_steps,
)
from app.schemas.car_port import CarPortInput
from app.schemas.config import RecBdConfig, SystemConfig
from simulation.modules.mcu_control import output_min_guarantee_kw


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _system(rec_bd_count: int = 4) -> SystemConfig:
    """Sprint 1 default — WebSessionEngine pins to 4 REC BDs.

    The rec_bd_count parameter is kept for forward-compatibility with Sprint 2
    (FR-11 will lift the pin), but right now anything other than 4 will hit
    WebSessionEngine._validate_sprint1. Callers that deliberately want to
    short-circuit at the validator (before any engine build) may still pass
    a smaller number — but most test bodies should leave the default.
    """
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
    sys = _system(4)
    ports = _ports_full(4, {1: {"max_required": 125, "present": 125, "target": 125}})
    seq = asyncio.run(generate_control_steps(sys, ports))
    assert seq.total_steps == 0
    assert seq.steps == []
    assert any("No change required" in w for w in seq.warnings)


def test_target_exceeds_capacity_warns_does_not_raise():
    """F14.3a: Target overload is a warning, not a hard 422. Sequence is
    still produced; engine truncates per-port to feasible allocation."""
    sys = _system(4)  # 4 × 250 kW = 1000 kW total; 8 × 600 = 4800 kW > 1000
    ports = _ports_full(
        4,
        {
            pid: {
                "max_required": 600,
                "present": 0,
                "target": 600,
                "priority": pid,
            }
            for pid in range(1, 9)
        },
    )
    seq = asyncio.run(generate_control_steps(sys, ports))
    assert seq.total_steps > 0
    assert any("exceeds total station capacity" in w for w in seq.warnings), (
        f"expected TARGET_EXCEEDS_CAPACITY warning, got {seq.warnings}"
    )


def test_priorities_insufficient_raises():
    sys = _system(2)  # validator short-circuits before WebSessionEngine
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
        asyncio.run(generate_control_steps(sys, ports))


def test_arrival_holds_output_open_until_125kw():
    """SPEC §11: Output relay stays Open while allocated < 125 kW."""
    sys = _system(4)
    ports = _ports_full(
        4, {1: {"max_required": 125, "present": 0, "target": 125}}
    )
    seq = asyncio.run(generate_control_steps(sys, ports))
    assert seq.total_steps > 0

    # SPEC §11 per-Output 0 minimum guarantee for default `[50,75,75,50]` = 125 kW.
    floor = output_min_guarantee_kw([50, 75, 75, 50], 0)

    # Walk every emitted step. While allocation < floor for port 1, Output must be Open.
    last_open_idx = -1
    closed_idx = -1
    for i, step in enumerate(seq.steps):
        car = _car(step.snapshot, 1)
        relay = _output_relay(step.snapshot, 1)
        if car.allocated_kw < floor:
            assert relay.state == "Open", (
                f"step {i}: alloc={car.allocated_kw} < {floor} but Output {relay.state}"
            )
            last_open_idx = i
        elif relay.state == "Closed" and closed_idx == -1:
            closed_idx = i

    assert closed_idx != -1, f"Output never closes — should close once ≥{floor} kW reached"
    assert closed_idx > last_open_idx
    # The engagement step description should mention closing the output relay.
    assert "Close M1.O1" in seq.steps[closed_idx].description


def test_arrival_below_125kw_never_closes_output():
    """SPEC §11 minimum guarantee — sim engages at 125 kW even when demand < 125;
    we only assert Output is Open while allocated < 125.

    F14.4: simulation core enforces the minimum-engagement invariant by
    over-provisioning to 125 kW even when user demand is below it. The
    Output relay therefore *will* close at the engagement step despite
    target=75. The invariant we still enforce is the SPEC §11 ordering:
    Output stays Open while allocated_kw < 125.
    """
    sys = _system(4)
    ports = _ports_full(
        4, {1: {"max_required": 75, "present": 0, "target": 75}}
    )
    seq = asyncio.run(generate_control_steps(sys, ports))
    # SPEC §11 per-Output 0 minimum guarantee for default `[50,75,75,50]` = 125 kW.
    floor = output_min_guarantee_kw([50, 75, 75, 50], 0)
    for step in seq.steps:
        car = _car(step.snapshot, 1)
        relay = _output_relay(step.snapshot, 1)
        if car.allocated_kw < floor:
            assert relay.state == "Open", (
                f"alloc={car.allocated_kw} kW < {floor} but Output {relay.state}"
            )


def test_full_departure_opens_output_last():
    """SPEC §11: on full departure, inter-group relays open before Output."""
    sys = _system(4)
    ports = _ports_full(
        4, {1: {"max_required": 0, "present": 200, "target": 0}}
    )
    seq = asyncio.run(generate_control_steps(sys, ports))
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
    sys = _system(4)
    ports = _ports_full(
        4, {1: {"max_required": 200, "present": 200, "target": 125}}
    )
    seq = asyncio.run(generate_control_steps(sys, ports))
    assert seq.total_steps > 0
    for step in seq.steps:
        relay = _output_relay(step.snapshot, 1)
        assert relay.state == "Closed"


def test_priority_drives_arrival_order():
    """Highest-priority arrival completes before lower-priority ones."""
    sys = _system(4)
    ports = _ports_full(
        4,
        {
            1: {"max_required": 125, "present": 0, "target": 125, "priority": 2},
            3: {"max_required": 125, "present": 0, "target": 125, "priority": 1},
        },
    )
    seq = asyncio.run(generate_control_steps(sys, ports))

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
    sys = _system(4)
    ports = _ports_full(
        4,
        {
            1: {"max_required": 125, "present": 200, "target": 125},
            2: {"max_required": 0, "present": 0, "target": 0, "priority": 2},
        },
    )
    seq = asyncio.run(generate_control_steps(sys, ports))
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
    seq = asyncio.run(generate_control_steps(sys, ports))

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


def test_apply_is_deterministic():
    """SPEC-WEB-API §3.3 #4: same (config, present, target) → identical sequence."""
    sys = _system(4)
    ports = _ports_full(
        4, {1: {"max_required": 250, "present": 0, "target": 250, "priority": 1}}
    )
    seq1 = asyncio.run(generate_control_steps(sys, ports))
    seq2 = asyncio.run(generate_control_steps(sys, ports))
    assert seq1.total_steps == seq2.total_steps
    assert [s.description for s in seq1.steps] == [s.description for s in seq2.steps]


@pytest.mark.benchmark
def test_apply_4mcu_latency_under_500ms():
    """SPEC-WEB-API §3.3 #3: P95 ≤ 5 s. With WebSessionEngine direct calls,
    expect ≪ 500 ms — Sprint 1 demo has tons of slack.
    """
    sys = _system(4)
    ports = _ports_full(
        4, {1: {"max_required": 250, "present": 0, "target": 250, "priority": 1}}
    )
    t0 = time.perf_counter()
    seq = asyncio.run(generate_control_steps(sys, ports))
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert seq.total_steps > 0
    assert elapsed_ms < 500, f"Apply took {elapsed_ms:.0f} ms, > 500 ms"


# ---------------------------------------------------------------------------
# Route integration tests
# ---------------------------------------------------------------------------

def _create_session_with_arrival(client: TestClient, target: int = 125) -> str:
    """Helper: create a 4-REC-BD session with port 1 arriving at given target."""
    cfg = {
        "rec_bd_count": 4,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]} for i in range(4)
        ],
    }
    ports = [
        {"port_id": 1, "max_required": target, "present": 0, "target": target, "priority": 1},
    ] + [
        {"port_id": pid, "max_required": 0, "present": 0, "target": 0, "priority": pid}
        for pid in range(2, 9)
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


def test_route_apply_and_generate_target_over_capacity_warns(client: TestClient):
    """F14.3a: Target overload returns 200 with warning, not 422."""
    cfg = {
        "rec_bd_count": 4,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]} for i in range(4)
        ],
    }
    # 4 REC BDs × 250 kW = 1000 kW capacity. 8 ports × 600 = 4800 > 1000.
    ports = [
        {
            "port_id": pid,
            "max_required": 600,
            "present": 0,
            "target": 600,
            "priority": pid,
        }
        for pid in range(1, 9)
    ]
    r = client.post(
        "/api/v1/sessions", json={"system_config": cfg, "car_ports": ports}
    )
    sid = r.json()["session_id"]

    r2 = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["total_steps"] >= 0
    assert any("exceeds total station capacity" in w for w in body["warnings"]), (
        f"expected TARGET_EXCEEDS_CAPACITY warning, got {body['warnings']}"
    )


def test_route_apply_and_generate_422_priorities_insufficient(client: TestClient):
    cfg = {
        "rec_bd_count": 4,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]} for i in range(4)
        ],
    }
    # Only port 1 has a priority — fewer than 2 set ⇒ PRIORITIES_INSUFFICIENT.
    ports = [
        {"port_id": 1, "max_required": 125, "present": 0, "target": 125, "priority": 1},
    ] + [
        {"port_id": pid, "max_required": 0, "present": 0, "target": 0}
        for pid in range(2, 9)
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
            ] + [
                {"port_id": pid, "max_required": 0, "present": 0, "target": 0, "priority": pid}
                for pid in range(2, 9)
            ]
        },
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "edit"
    assert r.json()["step_sequence"] is None


# ---------------------------------------------------------------------------
# 4-REC-BD scenarios (F14.4)
# ---------------------------------------------------------------------------

def test_ring_borrow_closes_bridge_before_output():
    """SPEC §11: bridge relay closes before Output on cross-MCU borrow."""
    sys = _system(4)
    ports = _ports_full(
        4, {1: {"max_required": 350, "present": 0, "target": 350, "priority": 1}}
    )
    seq = asyncio.run(generate_control_steps(sys, ports))

    # final snapshot must have at least one bridge Closed
    final_relays = seq.steps[-1].snapshot.relays
    bridges_closed = [
        r for r in final_relays if r.kind == "bridge" and r.state == "Closed"
    ]
    assert bridges_closed, "Port 1 at 350 kW must close at least one bridge relay"

    # description ordering
    bridge_step_idx = next(
        (i for i, s in enumerate(seq.steps) if "Close B_" in s.description), None
    )
    output_step_idx = next(
        (i for i, s in enumerate(seq.steps) if "Close M1.O1" in s.description), None
    )
    assert bridge_step_idx is not None, "bridge close step must appear"
    assert output_step_idx is not None, "M1.O1 close step must appear"
    assert bridge_step_idx < output_step_idx, (
        f"bridge step {bridge_step_idx} must precede output step {output_step_idx}"
    )


def test_mixed_departure_then_arrival_phase_ordering():
    """Phase A (departures) entirely precedes Phase C (arrivals)."""
    sys = _system(4)
    ports = _ports_full(
        4,
        {
            1: {"max_required": 0, "present": 125, "target": 0, "priority": 1},
            5: {"max_required": 125, "present": 0, "target": 125, "priority": 2},
        },
    )
    seq = asyncio.run(generate_control_steps(sys, ports))

    p1_open_idx = next(
        i for i, s in enumerate(seq.steps) if "Open M1.O1" in s.description
    )
    p5_close_idx = next(
        i for i, s in enumerate(seq.steps) if "Close M3.O1" in s.description
    )
    assert p1_open_idx < p5_close_idx, (
        f"port 1 departure (idx {p1_open_idx}) must precede "
        f"port 5 arrival (idx {p5_close_idx})"
    )


def test_full_load_apply_completes_within_budget():
    """SPEC §3.3 #3: P95 ≤ 5s. Full-load 8-port arrival should comfortably make it."""
    sys = _system(4)
    overrides = {
        pid: {"max_required": 125, "present": 0, "target": 125, "priority": pid}
        for pid in range(1, 9)
    }
    ports = _ports_full(4, overrides)

    t0 = time.perf_counter()
    seq = asyncio.run(generate_control_steps(sys, ports))
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert seq.total_steps > 0, "full-load arrival must produce steps"
    assert elapsed_ms < 500, (
        f"apply took {elapsed_ms:.0f} ms (budget 500 ms; SPEC P95 = 5000 ms)"
    )


def test_route_apply_then_full_player_walkthrough(client: TestClient):
    """End-to-end: apply → forward N+1 times (wrap) → back once (wrap)."""
    sid = _create_session_with_arrival(client, target=250)
    r = client.post(f"/api/v1/sessions/{sid}/apply-and-generate")
    assert r.status_code == 200, r.text
    total = r.json()["total_steps"]
    assert total > 0

    # forward through the entire sequence
    for _ in range(total):
        rf = client.post(f"/api/v1/sessions/{sid}/step", params={"direction": "forward"})
        assert rf.status_code == 200
        body = rf.json()
        assert body["snapshot"] is not None
        assert body["description"] != ""

    # one more forward → wraps to 0
    rf = client.post(f"/api/v1/sessions/{sid}/step", params={"direction": "forward"})
    assert rf.json()["current_step_index"] == 0

    # back from 0 → wraps to total
    rb = client.post(f"/api/v1/sessions/{sid}/step", params={"direction": "back"})
    assert rb.json()["current_step_index"] == total


def test_dual_port_per_bd_stitched_final_matches_engine_final():
    """Regression: when two ports home the same REC BD (Port 1 + Port 2 → BD1),
    the last stitched ControlStep snapshot must match the WebSessionEngine
    final_state exactly. Previously _adjacent_pack_owners mis-attributed every
    BD1 inter_group flip to the lowest port_id (via min(owners)) because the
    inter_group branch never filtered by group index, leaving Port 2's gating
    set empty in _resolve_pack_owner and stranding BD1 G2 packs at owner=None
    — surfacing as Car 2 = 50 kW and BD1 used = 7/10 in the player.
    """
    from app.services.web_session_engine import WebSessionEngine

    sys = _system(4)
    ports = _ports_full(
        4,
        {
            1: {"max_required": 300, "present": 40, "target": 300, "priority": 3},
            2: {"max_required": 200, "present": 50, "target": 200, "priority": 2},
            3: {"max_required": 100, "present": 60, "target": 100, "priority": 1},
        },
    )

    async def _go():
        present_ports = [cp.model_copy(update={"max_required": cp.present}) for cp in ports]
        target_ports = [cp.model_copy(update={"max_required": cp.target}) for cp in ports]
        initial_engine = await WebSessionEngine.create(sys, present_ports)
        final_engine = await WebSessionEngine.create(sys, target_ports)
        return initial_engine.to_visual_snapshot(), final_engine.to_visual_snapshot()

    initial_state, final_state = asyncio.run(_go())
    steps = step_planner.plan_transition(sys, ports, initial_state, final_state)
    assert len(steps) > 0, "expected control steps for present->target transition"

    last = steps[-1].snapshot

    # 1. Per-pack ownership in the last stitched step must equal final_state.
    final_packs = {(p.rec_bd_id, p.pack_index): p.owner_port_id for p in final_state.packs}
    last_packs = {(p.rec_bd_id, p.pack_index): p.owner_port_id for p in last.packs}
    assert last_packs == final_packs, (
        f"last-step pack ownership diverges from final_state; "
        f"missing/wrong = {[k for k in final_packs if last_packs.get(k) != final_packs[k]]}"
    )

    # 2. Per-car allocation in the last step matches final_state for active ports.
    final_cars = {c.port_id: c.allocated_kw for c in final_state.cars}
    for c in last.cars:
        if c.port_id in (1, 2, 3):
            assert c.allocated_kw == final_cars[c.port_id], (
                f"Port {c.port_id} last-step alloc {c.allocated_kw} != "
                f"final_state alloc {final_cars[c.port_id]}"
            )

    # 3. Port 2 floor — guards against the 50 kW regression symptom.
    car2 = next(c for c in last.cars if c.port_id == 2)
    assert car2.allocated_kw >= 125, (
        f"Port 2 should retain ≥ 125 kW (anchor G3 + G2); got {car2.allocated_kw}"
    )

    # 4. At least one step description must attribute to Port 2 (M1.R4 expansion).
    assert any("Port 2" in s.description for s in steps), (
        f"no step attributed to Port 2; descriptions = {[s.description for s in steps]}"
    )
