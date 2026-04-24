"""Validation endpoint tests — FR-08, FR-10, FR-11, FR-12, FR-13, FR-16."""
from __future__ import annotations

from fastapi.testclient import TestClient


# ---------- FR-11 module powers -----------------------------------------

def test_module_powers_valid(client: TestClient):
    r = client.post("/api/v1/validate/module-powers", json={"raw": "50, 75, 75, 50"})
    body = r.json()
    assert r.status_code == 200
    assert body["powers"] == [50, 75, 75, 50]
    assert body["total_capacity_kw"] == 250
    assert body["pack_count"] == 2 + 3 + 3 + 2
    assert body["errors"] == []


def test_module_powers_reject_not_multiple_of_25(client: TestClient):
    r = client.post("/api/v1/validate/module-powers", json={"raw": "50, 60, 75"})
    body = r.json()
    assert body["powers"] == []
    codes = {e["code"] for e in body["errors"]}
    assert "MODULE_POWER_NOT_MULTIPLE_OF_25" in codes


def test_module_powers_reject_out_of_range(client: TestClient):
    r = client.post("/api/v1/validate/module-powers", json={"raw": "25, 125"})
    codes = {e["code"] for e in r.json()["errors"]}
    assert "MODULE_POWER_OUT_OF_RANGE" in codes


# ---------- FR-12 car port normalization --------------------------------

def _cfg(rec_bd_count: int = 1) -> dict:
    return {
        "rec_bd_count": rec_bd_count,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]}
            for i in range(rec_bd_count)
        ],
    }


def test_car_port_clamp_and_round(client: TestClient):
    payload = {
        "batch": {
            "ports": [
                {"port_id": 1, "max_required": 630, "present": 0, "target": 0},
                {"port_id": 2, "max_required": -10, "present": 0, "target": 0},
                {"port_id": 3, "max_required": 130, "present": 0, "target": 0},
                {"port_id": 4, "max_required": 250, "present": 0, "target": 0},
            ]
        }
    }
    r = client.post("/api/v1/validate/car-ports", json=payload)
    body = r.json()
    assert r.status_code == 200
    by_id = {p["port_id"]: p for p in body["ports"]}
    assert by_id[1]["max_required"] == 600  # clamped above
    assert by_id[2]["max_required"] == 0    # clamped below
    assert by_id[3]["max_required"] == 125  # rounded down
    assert by_id[4]["max_required"] == 250
    warn_codes = {w["code"] for w in body["warnings"]}
    assert {"ABOVE_MAX", "BELOW_MIN", "NOT_MULTIPLE_OF_25"} <= warn_codes


# ---------- FR-16 priority rules ----------------------------------------

def test_priority_duplicate_rejected(client: TestClient):
    payload = {
        "batch": {
            "ports": [
                {"port_id": 1, "max_required": 0, "priority": 1},
                {"port_id": 2, "max_required": 0, "priority": 1},
            ]
        },
        "system_config": _cfg(1),
    }
    r = client.post("/api/v1/validate/car-ports", json=payload)
    codes = {e["code"] for e in r.json()["errors"]}
    assert "PRIORITY_DUPLICATE" in codes


def test_priority_out_of_range_rejected(client: TestClient):
    payload = {
        "batch": {
            "ports": [
                {"port_id": 1, "max_required": 0, "priority": 5},
                {"port_id": 2, "max_required": 0, "priority": 2},
            ]
        },
        "system_config": _cfg(1),
    }
    r = client.post("/api/v1/validate/car-ports", json=payload)
    codes = {e["code"] for e in r.json()["errors"]}
    assert "PRIORITY_OUT_OF_RANGE" in codes


def test_apply_ready_requires_two_priorities(client: TestClient):
    payload = {
        "batch": {
            "ports": [
                {"port_id": 1, "max_required": 0, "priority": 1},
                {"port_id": 2, "max_required": 0},
            ]
        },
        "system_config": _cfg(1),
    }
    body = client.post("/api/v1/validate/car-ports", json=payload).json()
    assert body["apply_ready"] is False

    payload["batch"]["ports"][1]["priority"] = 2
    body = client.post("/api/v1/validate/car-ports", json=payload).json()
    assert body["apply_ready"] is True


# ---------- FR-13 target-over-capacity ----------------------------------

def test_target_over_capacity_rejected(client: TestClient):
    # 1 REC BD = 250 kW. Two ports each targeting 200 kW → 400 kW > 250 kW.
    payload = {
        "batch": {
            "ports": [
                {"port_id": 1, "max_required": 200, "target": 200, "priority": 1},
                {"port_id": 2, "max_required": 200, "target": 200, "priority": 2},
            ]
        },
        "system_config": _cfg(1),
    }
    body = client.post("/api/v1/validate/car-ports", json=payload).json()
    codes = {e["code"] for e in body["errors"]}
    assert "TARGET_EXCEEDS_CAPACITY" in codes


# ---------- FR-10 system config -----------------------------------------

def test_system_config_valid(client: TestClient):
    r = client.post("/api/v1/validate/system-config", json=_cfg(4))
    body = r.json()
    assert r.status_code == 200
    assert body["errors"] == []
    assert body["total_capacity_kw"] == 4 * 250
    assert body["car_port_count"] == 8


def test_system_config_bad_module_power(client: TestClient):
    cfg = _cfg(1)
    cfg["rec_bds"][0]["module_powers"] = [50, 125]  # 125 > 100 max
    # This fails Pydantic field validation (RecBdConfig). Expect 422.
    r = client.post("/api/v1/validate/system-config", json=cfg)
    assert r.status_code == 422
