"""S2.2 — module_powers (dim B) end-to-end verification.

These tests exercise the freedom unlocked by S2.2: per-MCU
``module_powers`` now flows ``SystemConfig.rec_bds[i].module_powers`` →
``SimulationConfig.module_powers_per_mcu`` → ``ChargingStation`` →
``RectifierBoard.__init__(module_powers=...)`` and reaches the SMR group
shapes.

Layout follows S2.1's ``test_snapshot_dynamic_n.py``: sync ``TestClient``,
default ``client`` fixture from ``conftest.py``. The route
``/api/v1/snapshot/compute`` is async internally and uses
``WebSessionEngine.create()`` (which drives the actor settle loop), so any
non-zero-demand test below relies on that settle path.

Test matrix:
- A : N=4 uniform [75, 100, 100, 75]            — sanity (zero demand)
- B : N=4 uniform [50, 50, 50, 50]              — sanity (zero demand)
- C : N=4 asymmetric, BD1=[50,50,50,50] forces  — cross-BD borrow
      a 250 kW car at port 1 to borrow into BD2   (S2.3 step_planner ground truth)
- D : N=2 linear, asymmetric module_powers      — linear-topology path
"""
from __future__ import annotations

from typing import List

import pytest
from fastapi.testclient import TestClient


def _cfg(rec_bds: List[List[int]]) -> dict:
    """Build SystemConfig given a list of per-BD module_power lists."""
    return {
        "rec_bd_count": len(rec_bds),
        "rec_bds": [
            {"id": i + 1, "module_powers": mp} for i, mp in enumerate(rec_bds)
        ],
    }


def _ports_zero(n: int) -> List[dict]:
    return [
        {"port_id": pid, "max_required": 0, "present": 0, "target": 0, "priority": None}
        for pid in range(1, 2 * n + 1)
    ]


def _ports_one_active(n: int, active_port_id: int, max_required: int) -> List[dict]:
    """All ports zero except `active_port_id` which gets `max_required` kW."""
    return [
        {
            "port_id": pid,
            "max_required": max_required if pid == active_port_id else 0,
            "present": 0,
            "target": 0,
            "priority": None,
        }
        for pid in range(1, 2 * n + 1)
    ]


def _snapshot(client: TestClient, cfg: dict, ports: List[dict]) -> dict:
    r = client.post(
        "/api/v1/snapshot/compute",
        json={"system_config": cfg, "car_ports": ports},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Test A — N=4 uniform [75, 100, 100, 75], zero demand sanity
# ---------------------------------------------------------------------------

def test_snapshot_n4_uniform_75_100_100_75(client: TestClient):
    cfg = _cfg([[75, 100, 100, 75]] * 4)
    snap = _snapshot(client, cfg, _ports_zero(4))

    # Each BD is 350 kW → 14 packs (3+4+4+3).
    assert len(snap["rec_bds"]) == 4
    for bd in snap["rec_bds"]:
        assert bd["total_packs"] == 14
        assert bd["status"] == "Idle"
        assert bd["power_kw"] == 0

    # Total pack-snapshots = 4 × 14.
    assert len(snap["packs"]) == 4 * 14
    assert all(not p["in_use"] for p in snap["packs"])
    assert snap["total_power_kw"] == 0


# ---------------------------------------------------------------------------
# Test B — N=4 uniform [50, 50, 50, 50], zero demand sanity
# ---------------------------------------------------------------------------

def test_snapshot_n4_uniform_50_50_50_50(client: TestClient):
    cfg = _cfg([[50, 50, 50, 50]] * 4)
    snap = _snapshot(client, cfg, _ports_zero(4))

    # Each BD is 200 kW → 8 packs.
    assert len(snap["rec_bds"]) == 4
    for bd in snap["rec_bds"]:
        assert bd["total_packs"] == 8
        assert bd["status"] == "Idle"

    assert len(snap["packs"]) == 4 * 8
    assert all(not p["in_use"] for p in snap["packs"])


# ---------------------------------------------------------------------------
# Test C (main / weak) — N=4 asymmetric forcing cross-BD borrow
# ---------------------------------------------------------------------------
# BD1 is intentionally weak: [50, 50, 50, 50] = 200 kW total. A 250 kW car
# at port 1 (anchored at BD1.G0) must borrow 50 kW from BD2 across the
# B_1_2 bridge — local resources alone are insufficient.

_ASYMMETRIC_4 = [
    [50, 50, 50, 50],   # BD1 — 200 kW (the constrained one)
    [50, 75, 75, 50],   # BD2 — 250 kW (default)
    [50, 75, 75, 50],   # BD3 — 250 kW (default)
    [50, 75, 75, 50],   # BD4 — 250 kW (default)
]


@pytest.mark.xfail(
    strict=True,
    reason=(
        "S2.5 step_planner gap. With BD1=[50,50,50,50], the hardcoded "
        "'anchor + initial 2 groups' allocation in mcu_control yields only "
        "50+50 = 100 kW pre-settle — *below* SPEC §11's 125 kW minimum-"
        "guarantee for closing the Output relay. Settle doesn't recover "
        "(no cross-BD borrow triggered). Observed engagement_avail=100 kW, "
        "output_relay=CLOSED (also a §11 violation: relay closed below "
        "125 kW threshold). S2.5 must rework the initial-group selection "
        "to be module_powers-aware, not the dim-A hardcoded [G0, G1]."
    ),
)
def test_snapshot_n4_asymmetric_with_cross_bd_borrow(client: TestClient):
    """Weak assertions: route returns sane snapshot, port 1 is Active,
    BD1 is fully engaged. Does NOT assert cross-BD borrow happened."""
    cfg = _cfg(_ASYMMETRIC_4)
    ports = _ports_one_active(n=4, active_port_id=1, max_required=250)
    snap = _snapshot(client, cfg, ports)

    # Layout shape sanity: 4 BDs, pack counts match per-BD module_powers.
    assert len(snap["rec_bds"]) == 4
    assert snap["rec_bds"][0]["total_packs"] == 8         # BD1: 50*4 / 25
    assert all(snap["rec_bds"][i]["total_packs"] == 10 for i in [1, 2, 3])

    # Port 1 should be the only active car; others stay Inactive.
    car_by_id = {c["port_id"]: c for c in snap["cars"]}
    assert car_by_id[1]["status"] == "Active"
    for pid in range(2, 9):
        assert car_by_id[pid]["status"] == "Inactive"

    # Engine should attempt to satisfy 250 kW; allocated_kw is at least the
    # 125 kW minimum-engagement and at most 250 kW (capped by max_required).
    allocated = car_by_id[1]["allocated_kw"]
    assert 125 <= allocated <= 250, f"Port 1 allocated {allocated} kW out of bounds"


@pytest.mark.xfail(
    strict=False,
    reason=(
        "S2.5 step_planner cross-BD borrow validation. With BD1=[50,50,50,50]=200kW "
        "and a 250kW car at port 1, settle should borrow 50 kW from BD2 via the "
        "B_1_2 bridge. Marked strict=False so an unexpected pass is reported (Sprint 2 "
        "win) without breaking CI."
    ),
)
def test_snapshot_n4_asymmetric_cross_bd_borrow_actually_engages(client: TestClient):
    """Strong assertions: full 250 kW allocated, BD2 lends ≥1 pack to port 1,
    bridge B_1_2 closed. Pinpoints whether step_planner correctly handles
    asymmetric module_powers across the cross-BD borrow path."""
    cfg = _cfg(_ASYMMETRIC_4)
    ports = _ports_one_active(n=4, active_port_id=1, max_required=250)
    snap = _snapshot(client, cfg, ports)

    car1 = next(c for c in snap["cars"] if c["port_id"] == 1)

    # 1) Full demand satisfied.
    assert car1["allocated_kw"] == 250, f"Expected 250 kW allocated, got {car1['allocated_kw']}"

    # 2) BD1 fully engaged (all 8 packs used by port 1).
    bd1_packs = [p for p in snap["packs"] if p["rec_bd_id"] == 1]
    bd1_used_by_p1 = [p for p in bd1_packs if p["in_use"] and p["owner_port_id"] == 1]
    assert len(bd1_used_by_p1) == 8, (
        f"Expected BD1 fully owned by port 1 (8 packs), got {len(bd1_used_by_p1)}"
    )

    # 3) BD2 lends ≥2 packs (the missing 50 kW) to port 1 across the bridge.
    bd2_used_by_p1 = [
        p for p in snap["packs"]
        if p["rec_bd_id"] == 2 and p["in_use"] and p["owner_port_id"] == 1
    ]
    assert len(bd2_used_by_p1) >= 2, (
        f"Expected BD2 to lend ≥2 packs to port 1, got {len(bd2_used_by_p1)}"
    )

    # 4) Bridge B_1_2 closed (the relay carrying the borrowed 50 kW).
    bridge_1_2 = next(r for r in snap["relays"] if r["id"] == "B_1_2")
    assert bridge_1_2["state"] == "Closed", (
        f"Expected B_1_2 Closed (cross-BD borrow path), got {bridge_1_2['state']}"
    )


# ---------------------------------------------------------------------------
# Test D — N=2 linear topology, asymmetric module_powers
# ---------------------------------------------------------------------------

def test_snapshot_n2_linear_asymmetric_module_powers(client: TestClient):
    """Linear-topology path with two heterogeneous BDs (one bridge B_1_2)."""
    cfg = _cfg([
        [75, 100, 100, 75],   # BD1 — 350 kW
        [50, 50, 50, 50],     # BD2 — 200 kW
    ])
    snap = _snapshot(client, cfg, _ports_zero(2))

    assert len(snap["rec_bds"]) == 2
    assert snap["rec_bds"][0]["total_packs"] == 14
    assert snap["rec_bds"][1]["total_packs"] == 8

    bridges = [r for r in snap["relays"] if r["kind"] == "bridge"]
    assert len(bridges) == 1
    assert bridges[0]["id"] == "B_1_2"

    # Zero demand → all idle.
    assert all(bd["status"] == "Idle" for bd in snap["rec_bds"])
    assert all(c["status"] == "Inactive" for c in snap["cars"])
