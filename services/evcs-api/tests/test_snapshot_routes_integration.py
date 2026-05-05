"""Integration tests for FR-09 snapshot routes after F09.3 async switch.

Verifies that:

1. ``POST /api/v1/snapshot/compute`` and ``GET /api/v1/sessions/{id}/snapshot``
   still behave correctly after both became ``async def`` and route through
   ``compute_snapshot_async``.
2. Capacity-warning surfacing — overload returns **200 + warning**, not 4xx
   (FR-09 is mid-edit; soft warning is the right UX. FR-14 has its own
   hard ``TARGET_EXCEEDS_CAPACITY``).
3. The PATCH → GET-snapshot loop works end-to-end (the canonical FR-09 flow).
"""
from __future__ import annotations

from typing import List, Tuple

from fastapi.testclient import TestClient


def _cfg_4mcu() -> dict:
    """Sprint 1 default config: 4 MCU × [50,75,75,50] = 1000 kW."""
    return {
        "rec_bd_count": 4,
        "rec_bds": [{"id": i + 1, "module_powers": [50, 75, 75, 50]} for i in range(4)],
    }


def _ports(specs: List[Tuple[int, int]]) -> List[dict]:
    """specs: list of (port_id, max_required)."""
    return [
        {
            "port_id": pid,
            "max_required": mr,
            "present": 0,
            "target": 0,
            "priority": None,
        }
        for pid, mr in specs
    ]


def _full_ports(overrides: List[Tuple[int, int]]) -> List[dict]:
    base = {pid: (pid, 0) for pid in range(1, 9)}
    for pid, mr in overrides:
        base[pid] = (pid, mr)
    return _ports(list(base.values()))


# ── POST /snapshot/compute ────────────────────────────────────────────────


class TestSnapshotComputeRoute:
    """POST /api/v1/snapshot/compute — stateless recompute path."""

    def test_returns_200_with_visual_snapshot(self, client: TestClient):
        """Happy path: 4 MCU + single port 125 kW → 200 + valid snapshot."""
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([(1, 125)]),
        }
        r = client.post("/api/v1/snapshot/compute", json=body)
        assert r.status_code == 200, r.text
        snap = r.json()
        assert snap["total_power_kw"] >= 125
        assert len(snap["cars"]) == 8
        # Port 1 should be Active.
        car1 = next(c for c in snap["cars"] if c["port_id"] == 1)
        assert car1["status"] == "Active"

    def test_overcapacity_returns_200_with_warning(self, client: TestClient):
        """FR-09 capacity overflow: 200 + warning, NOT 4xx."""
        # 8 ports × 200 kW = 1600 kW > 1000 kW capacity.
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _ports([(pid, 200) for pid in range(1, 9)]),
        }
        r = client.post("/api/v1/snapshot/compute", json=body)
        assert r.status_code == 200, "FR-09 path should NOT hard-fail on overcapacity"
        snap = r.json()
        assert any(
            "exceeds" in w.lower() and "max required" in w.lower()
            for w in snap["warnings"]
        ), f"expected capacity warning, got: {snap['warnings']}"

    def test_undercapacity_no_warning(self, client: TestClient):
        """Normal load → no capacity warning."""
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([(1, 125)]),
        }
        r = client.post("/api/v1/snapshot/compute", json=body)
        assert r.status_code == 200
        snap = r.json()
        assert not any("exceeds" in w.lower() for w in snap["warnings"])

    def test_low_demand_engages_with_125kw_floor(self, client: TestClient):
        """SPEC §11: even max_required=50 engages and gets 125 kW (hardware floor)."""
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([(1, 50)]),
        }
        r = client.post("/api/v1/snapshot/compute", json=body)
        assert r.status_code == 200
        snap = r.json()
        car1 = next(c for c in snap["cars"] if c["port_id"] == 1)
        assert car1["status"] == "Active"
        assert car1["allocated_kw"] >= 125
        assert car1["max_required"] == 50  # user input preserved

    def test_at_min_engage_125_kw(self, client: TestClient):
        """Boundary: exactly 125 kW engages cleanly."""
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([(1, 125)]),
        }
        r = client.post("/api/v1/snapshot/compute", json=body)
        assert r.status_code == 200
        snap = r.json()
        car1 = next(c for c in snap["cars"] if c["port_id"] == 1)
        assert car1["status"] == "Active"
        assert car1["allocated_kw"] >= 125

    def test_low_demand_with_neighbor_borrow(self, client: TestClient):
        """P1=50 (engages at 125) + P2=300 (cross-MCU borrow) — both correct."""
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _ports([
                (1, 50), (2, 300), (3, 0), (4, 0),
                (5, 0), (6, 0), (7, 0), (8, 0),
            ]),
        }
        r = client.post("/api/v1/snapshot/compute", json=body)
        assert r.status_code == 200
        snap = r.json()
        cars_by_id = {c["port_id"]: c for c in snap["cars"]}

        assert cars_by_id[1]["status"] == "Active"
        assert cars_by_id[1]["allocated_kw"] >= 125
        assert cars_by_id[1]["max_required"] == 50

        assert cars_by_id[2]["status"] == "Active"
        assert cars_by_id[2]["allocated_kw"] >= 300

    def test_zero_demand_stays_idle(self, client: TestClient):
        """max_required=0 must not engage — distinct from low-demand."""
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([]),  # all zeros
        }
        r = client.post("/api/v1/snapshot/compute", json=body)
        assert r.status_code == 200
        snap = r.json()
        for c in snap["cars"]:
            assert c["status"] == "Inactive"
            assert c["allocated_kw"] == 0


# ── GET /sessions/{id}/snapshot ───────────────────────────────────────────


class TestSessionSnapshotRoute:
    """GET /api/v1/sessions/{id}/snapshot — stateful path."""

    def test_after_create_returns_snapshot(self, client: TestClient):
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([(1, 125)]),
        }
        create_resp = client.post("/api/v1/sessions", json=body)
        assert create_resp.status_code in (200, 201), create_resp.text
        session_id = create_resp.json()["session_id"]

        snap_resp = client.get(f"/api/v1/sessions/{session_id}/snapshot")
        assert snap_resp.status_code == 200, snap_resp.text
        snap = snap_resp.json()
        assert snap["total_power_kw"] >= 125

    def test_404_for_unknown_session(self, client: TestClient):
        r = client.get("/api/v1/sessions/nonexistent_id/snapshot")
        assert r.status_code == 404

    def test_after_patch_max_required_returns_updated_snapshot(
        self, client: TestClient
    ):
        """The FR-09 core flow: PATCH session → GET snapshot reflects new demand."""
        initial_body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([]),
        }
        create_resp = client.post("/api/v1/sessions", json=initial_body)
        sid = create_resp.json()["session_id"]

        snap0 = client.get(f"/api/v1/sessions/{sid}/snapshot").json()
        assert snap0["total_power_kw"] == 0

        patch_resp = client.patch(
            f"/api/v1/sessions/{sid}",
            json={"car_ports": _full_ports([(1, 125)])},
        )
        assert patch_resp.status_code == 200, patch_resp.text

        snap1 = client.get(f"/api/v1/sessions/{sid}/snapshot").json()
        assert snap1["total_power_kw"] >= 125

    def test_session_snapshot_overcapacity_returns_200_with_warning(
        self, client: TestClient
    ):
        """Stateful path also surfaces the capacity warning."""
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _ports([(pid, 200) for pid in range(1, 9)]),
        }
        create_resp = client.post("/api/v1/sessions", json=body)
        sid = create_resp.json()["session_id"]
        snap_resp = client.get(f"/api/v1/sessions/{sid}/snapshot")
        assert snap_resp.status_code == 200
        snap = snap_resp.json()
        assert any("exceeds" in w.lower() for w in snap["warnings"])
