"""Visual snapshot tests — FR-02, FR-03, FR-04, FR-05, FR-09, FR-16."""
from __future__ import annotations

from typing import Dict, List

from fastapi.testclient import TestClient


def _cfg(n: int = 4) -> dict:
    return {
        "rec_bd_count": n,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]}  # 250 kW / 10 packs per REC BD
            for i in range(n)
        ],
    }


def _ports(specs: List[tuple]) -> List[dict]:
    """specs: List of (port_id, max_required, priority_or_None)."""
    return [
        {"port_id": pid, "max_required": mr, "present": 0, "target": 0, "priority": pr}
        for pid, mr, pr in specs
    ]


def _snapshot(client: TestClient, cfg: dict, ports: List[dict]) -> dict:
    r = client.post(
        "/api/v1/snapshot/compute",
        json={"system_config": cfg, "car_ports": ports},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _packs_owned_by(snap: dict, port_id: int) -> List[tuple]:
    return [
        (p["rec_bd_id"], p["pack_index"])
        for p in snap["packs"]
        if p["owner_port_id"] == port_id
    ]


def _relay(snap: dict, rid: str) -> dict:
    return next(r for r in snap["relays"] if r["id"] == rid)


# ---------------------------------------------------------------------------
# Basic allocation
# ---------------------------------------------------------------------------

def test_zero_demand_all_idle(client: TestClient):
    snap = _snapshot(client, _cfg(1), _ports([(1, 0, None), (2, 0, None)]))
    assert all(bd["status"] == "Idle" for bd in snap["rec_bds"])
    assert all(c["status"] == "Inactive" for c in snap["cars"])
    assert snap["total_power_kw"] == 0
    # Every relay open → every relay white.
    assert all(r["state"] == "Open" for r in snap["relays"])


def test_single_port_claims_packs_from_home(client: TestClient):
    # Port 1 of REC BD 1 wants 125 kW → 5 packs, all from REC BD 1 (home has 10).
    snap = _snapshot(client, _cfg(2), _ports([(1, 125, None), (2, 0, None), (3, 0, None), (4, 0, None)]))
    owned = _packs_owned_by(snap, 1)
    assert len(owned) == 5
    assert all(b == 1 for b, _ in owned)
    # Port 1 anchors at pack 0 → takes packs 0..4.
    assert sorted(p for _, p in owned) == [0, 1, 2, 3, 4]

    bd1 = next(bd for bd in snap["rec_bds"] if bd["id"] == 1)
    assert bd1["power_kw"] == 125 and bd1["used_packs"] == 5 and bd1["status"] == "Occupied"
    assert _relay(snap, "M1.O1")["state"] == "Closed"
    # Bridge stays open since allocation is purely local.
    assert _relay(snap, "B_1_2")["state"] == "Open"


def test_port_two_anchors_at_far_end(client: TestClient):
    # Port 2 = the 'other' port of REC BD 1 → anchor at last pack.
    snap = _snapshot(client, _cfg(1), _ports([(1, 0, None), (2, 75, None)]))
    owned = _packs_owned_by(snap, 2)
    # 75 kW = 3 packs, taken from the far end of REC BD 1 (packs 9, 8, 7).
    assert sorted(p for _, p in owned) == [7, 8, 9]


# ---------------------------------------------------------------------------
# Cross-REC-BD borrow (bridge closes)
# ---------------------------------------------------------------------------

def test_overflow_borrows_from_right_neighbor(client: TestClient):
    # Port 1 wants 400 kW = 16 packs; home REC BD 1 has only 10. Need 6 more from neighbors.
    # SPEC §2.2 priority: right (REC BD 2) first.
    snap = _snapshot(client, _cfg(4), _ports([(1, 400, 1), (2, 0, 2), (3, 0, 3), (4, 0, 4), (5, 0, 5), (6, 0, 6), (7, 0, 7), (8, 0, 8)]))
    owned = _packs_owned_by(snap, 1)
    assert len(owned) == 16
    bds_used = {b for b, _ in owned}
    assert 1 in bds_used  # home
    assert 2 in bds_used  # right neighbor (borrowed from)
    # Bridge B_1_2 closes because port 1 (home=REC BD 1) uses packs on REC BD 2.
    assert _relay(snap, "B_1_2")["state"] == "Closed"
    # Left bridge B_4_1 stays open (right was enough).
    assert _relay(snap, "B_4_1")["state"] == "Open"


# ---------------------------------------------------------------------------
# FR-03 pack color = consuming port's home REC BD color
# ---------------------------------------------------------------------------

def test_pack_color_follows_consumer(client: TestClient):
    snap = _snapshot(client, _cfg(2), _ports([(1, 300, 1), (2, 0, 2), (3, 0, 3), (4, 0, 4)]))
    color_by_bd = {bd["id"]: bd["color"] for bd in snap["rec_bds"]}
    # Some pack in REC BD 2 gets borrowed by port 1 (home REC BD 1) → it shows REC BD 1's color.
    borrowed = [
        p for p in snap["packs"]
        if p["rec_bd_id"] == 2 and p["owner_port_id"] == 1
    ]
    assert borrowed, "port 1 should have borrowed packs from REC BD 2"
    for p in borrowed:
        assert p["color"] == color_by_bd[1]


# ---------------------------------------------------------------------------
# FR-04 inter-group relay closes when one port spans two groups
# ---------------------------------------------------------------------------

def test_inter_group_relay_closes_when_spanning(client: TestClient):
    # Port 1 with 75 kW = 3 packs. REC BD 1 module 0 has 2 packs (0,1). So pack 2
    # is consumed from module 1 → inter-group relay R2 (between mod 0 and mod 1) closes.
    snap = _snapshot(client, _cfg(1), _ports([(1, 75, None), (2, 0, None)]))
    assert _relay(snap, "M1.R2")["state"] == "Closed"
    assert _relay(snap, "M1.R3")["state"] == "Open"  # didn't span into mod 2
    assert _relay(snap, "M1.R4")["state"] == "Open"


def test_inter_group_relay_open_when_confined_to_one_group(client: TestClient):
    # Port 1 with 50 kW = 2 packs — fills module 0 exactly, no R2 close.
    snap = _snapshot(client, _cfg(1), _ports([(1, 50, None), (2, 0, None)]))
    assert _relay(snap, "M1.R2")["state"] == "Open"


# ---------------------------------------------------------------------------
# FR-05 car color
# ---------------------------------------------------------------------------

def test_car_active_when_allocated(client: TestClient):
    snap = _snapshot(client, _cfg(1), _ports([(1, 125, None), (2, 0, None)]))
    c1 = next(c for c in snap["cars"] if c["port_id"] == 1)
    c2 = next(c for c in snap["cars"] if c["port_id"] == 2)
    assert c1["status"] == "Active" and c1["allocated_kw"] == 125
    assert c2["status"] == "Inactive" and c2["allocated_kw"] == 0


# ---------------------------------------------------------------------------
# FR-16 priority ordering
# ---------------------------------------------------------------------------

def test_priority_determines_allocation_order(client: TestClient):
    # 2 REC BDs = 20 packs, 500 kW. Two ports both want 300 kW (= 12 packs) →
    # 24 demanded, 20 supplied. Port 2 has priority 1 (wins), port 1 has priority 2.
    snap = _snapshot(
        client,
        _cfg(2),
        _ports([(1, 300, 2), (2, 300, 1), (3, 0, 3), (4, 0, 4)]),
    )
    owned_p1 = _packs_owned_by(snap, 1)
    owned_p2 = _packs_owned_by(snap, 2)
    # Port 2 (priority 1) should be fully satisfied: 12 packs.
    assert len(owned_p2) == 12, f"expected 12 packs for priority-1 port, got {len(owned_p2)}"
    # Port 1 gets what's left: 20 - 12 = 8 packs.
    assert len(owned_p1) == 8
    # Warning should flag the shortfall for port 1.
    assert any("Car Port 1" in w for w in snap["warnings"])


def test_priority_higher_number_still_gets_nonzero_when_capacity_allows(client: TestClient):
    # Same config, but both want 125 kW → both fit, priority-order doesn't starve anyone.
    snap = _snapshot(
        client,
        _cfg(2),
        _ports([(1, 125, 2), (2, 125, 1), (3, 0, 3), (4, 0, 4)]),
    )
    assert len(_packs_owned_by(snap, 1)) == 5
    assert len(_packs_owned_by(snap, 2)) == 5
    assert snap["warnings"] == []


# ---------------------------------------------------------------------------
# FR-09 recompute: same config, different Max Required → different snapshot
# ---------------------------------------------------------------------------

def test_snapshot_reflects_max_required_change(client: TestClient):
    cfg = _cfg(1)
    snap_a = _snapshot(client, cfg, _ports([(1, 0, None), (2, 0, None)]))
    snap_b = _snapshot(client, cfg, _ports([(1, 125, None), (2, 0, None)]))
    assert snap_a["total_power_kw"] == 0
    assert snap_b["total_power_kw"] == 125
    assert snap_a["rec_bds"][0]["status"] == "Idle"
    assert snap_b["rec_bds"][0]["status"] == "Occupied"


# ---------------------------------------------------------------------------
# Capacity shortage produces a warning
# ---------------------------------------------------------------------------

def test_oversubscribed_emits_warnings(client: TestClient):
    # 1 REC BD = 250 kW capacity. Two ports requesting 200 each → total 400 > 250.
    snap = _snapshot(client, _cfg(1), _ports([(1, 200, 1), (2, 200, 2)]))
    assert snap["total_requested_kw"] == 400
    assert snap["total_power_kw"] == 250  # full station delivered
    assert any("only" in w or "starved" in w for w in snap["warnings"])


# ---------------------------------------------------------------------------
# Session-bound snapshot
# ---------------------------------------------------------------------------

def test_session_snapshot_reflects_stored_state(client: TestClient):
    cfg = _cfg(2)
    r = client.post(
        "/api/v1/sessions",
        json={"system_config": cfg},
    )
    sid = r.json()["session_id"]

    # No car_ports yet → zero power.
    snap0 = client.get(f"/api/v1/sessions/{sid}/snapshot").json()
    assert snap0["total_power_kw"] == 0

    # PATCH car_ports, then re-fetch the snapshot (FR-09).
    ports = _ports([(1, 125, 1), (2, 0, 2), (3, 0, 3), (4, 0, 4)])
    client.patch(f"/api/v1/sessions/{sid}", json={"car_ports": ports})

    snap1 = client.get(f"/api/v1/sessions/{sid}/snapshot").json()
    assert snap1["total_power_kw"] == 125
    assert snap1["cars"][0]["status"] == "Active"


def test_session_snapshot_404_for_missing_session(client: TestClient):
    r = client.get("/api/v1/sessions/nope/snapshot")
    assert r.status_code == 404
