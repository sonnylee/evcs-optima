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

    def test_user_sequence_engage_release_increment_decrement(self, client: TestClient):
        """SPEC §6.2 regression: rebuild-engine across +25/-25 sequence.

        Pins behaviour reported during F09.5c review. F09.5c attempted a 125 kW
        demand floor that broke the natural release path; this regression
        catches any future reintroduction of that mistake.

        Module config: 4 MCU × [50, 75, 75, 50] per REC BD.
        Anchor for O0 is G0+G1 = 50+75 = 125 kW.

        | Step           | max | expected alloc | rationale                                          |
        |----------------|-----|----------------|----------------------------------------------------|
        | start          |   0 |   0 | idle                                                              |
        | +25 (engage)   |  25 |  50 | settle releases G1 (avail-demand=100 >= edge=75)                  |
        | +25            |  50 |  50 | (avail=50, demand=50): no further release                         |
        | -25            |  25 |  50 | (avail=50, demand=25): edge=G0=50 > 25, NO release                |
        | -25 (idle)     |   0 |   0 | output relay opens                                                |

        Key non-obvious step: "-25 to 25" does NOT release further — edge is
        now G0 (the anchor), which cannot be released without disengaging
        the Output entirely.
        """
        cfg = _cfg_4mcu()

        def _alloc_for(max_kw: int) -> int:
            if max_kw == 0:
                ports = _full_ports([])
            else:
                ports = _full_ports([(1, max_kw)])
            r = client.post(
                "/api/v1/snapshot/compute",
                json={"system_config": cfg, "car_ports": ports},
            )
            assert r.status_code == 200, r.text
            car1 = next(c for c in r.json()["cars"] if c["port_id"] == 1)
            return car1["allocated_kw"]

        assert _alloc_for(0) == 0, "start: idle, alloc=0"
        assert _alloc_for(25) == 50, "+25 engage: settles to G0=50 after §6.2 release"
        assert _alloc_for(50) == 50, "+25 to 50: holds at G0=50, no release possible"
        assert _alloc_for(25) == 50, "-25 to 25: edge=G0=50 > (50-25=25), NO further release"
        assert _alloc_for(0) == 0, "-25 to 0: idle"

    def test_repeated_patches_are_deterministic(self, client: TestClient):
        """FR-09 rebuild-engine guarantee: same final state ⇒ same snapshot.

        PATCH sequence A→B→C and direct PATCH C should both yield snapshot
        bit-identical at the visible payload level. This is the core promise
        of the rebuild-engine throwaway strategy — no SessionStore stale
        state should leak between PATCHes.
        """
        body = {
            "system_config": _cfg_4mcu(),
            "car_ports": _full_ports([]),
        }
        # Path 1: incremental PATCHes 50 → 75 → 125
        sid_a = client.post("/api/v1/sessions", json=body).json()["session_id"]
        for mr in (50, 75, 125):
            client.patch(
                f"/api/v1/sessions/{sid_a}",
                json={"car_ports": _full_ports([(1, mr)])},
            )
        snap_a = client.get(f"/api/v1/sessions/{sid_a}/snapshot").json()

        # Path 2: single PATCH directly to 125
        sid_b = client.post("/api/v1/sessions", json=body).json()["session_id"]
        client.patch(
            f"/api/v1/sessions/{sid_b}",
            json={"car_ports": _full_ports([(1, 125)])},
        )
        snap_b = client.get(f"/api/v1/sessions/{sid_b}/snapshot").json()

        assert snap_a["total_power_kw"] == snap_b["total_power_kw"]
        assert snap_a["cars"] == snap_b["cars"]
        assert snap_a["packs"] == snap_b["packs"]
        assert snap_a["relays"] == snap_b["relays"]


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
