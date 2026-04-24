"""Session CRUD tests — FR-09, FR-14, FR-15 (store only; step generation is Phase 3)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _cfg() -> dict:
    return {
        "rec_bd_count": 2,
        "rec_bds": [
            {"id": 1, "module_powers": [50, 75, 75, 50]},
            {"id": 2, "module_powers": [50, 75, 75, 50]},
        ],
    }


def test_create_get_list_delete(client: TestClient):
    r = client.post("/api/v1/sessions", json={"system_config": _cfg()})
    assert r.status_code == 201
    sid = r.json()["session_id"]

    r2 = client.get(f"/api/v1/sessions/{sid}")
    assert r2.status_code == 200
    assert r2.json()["system_config"]["rec_bd_count"] == 2

    r3 = client.get("/api/v1/sessions")
    assert sid in r3.json()

    r4 = client.delete(f"/api/v1/sessions/{sid}")
    assert r4.status_code == 204

    r5 = client.get(f"/api/v1/sessions/{sid}")
    assert r5.status_code == 404


def test_patch_invalidates_step_sequence_state(client: TestClient):
    r = client.post("/api/v1/sessions", json={"system_config": _cfg()})
    sid = r.json()["session_id"]

    # PATCH with new car_ports — mode should remain 'edit'.
    ports = [
        {"port_id": i, "max_required": 125, "present": 0, "target": 125, "priority": i}
        for i in range(1, 5)
    ]
    r2 = client.patch(f"/api/v1/sessions/{sid}", json={"car_ports": ports})
    assert r2.status_code == 200
    assert r2.json()["mode"] == "edit"
    assert len(r2.json()["car_ports"]) == 4


def test_create_rejects_bad_config(client: TestClient):
    bad = {
        "rec_bd_count": 13,  # > REC_BD_MAX
        "rec_bds": [{"id": 1, "module_powers": [50]}],
    }
    r = client.post("/api/v1/sessions", json={"system_config": bad})
    assert r.status_code == 422
