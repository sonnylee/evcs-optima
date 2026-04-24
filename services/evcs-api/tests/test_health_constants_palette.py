"""Smoke tests for /health, /constants, /palette (FR-01, FR-08, FR-10, FR-11)."""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_health(client: TestClient):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_constants_bounds(client: TestClient):
    r = client.get("/api/v1/constants")
    assert r.status_code == 200
    body = r.json()
    assert body["max_required"] == {"min": 0, "max": 600, "step": 25}
    assert body["rec_bd"]["min"] == 1 and body["rec_bd"]["max"] == 12
    assert body["rec_bd"]["default"] == 4
    assert body["module_power"] == {"min": 50, "max": 100, "step": 25}


def test_palette_default_cycle(client: TestClient):
    r = client.get("/api/v1/palette?count=6&cycle=true")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 6
    colors = body["rec_bd_colors"]
    assert len(colors) == 6
    # 4-color cycle repeats (FR-10)
    assert colors[0] == colors[4]
    assert colors[1] == colors[5]


def test_palette_extended(client: TestClient):
    r = client.get("/api/v1/palette?count=8&cycle=false")
    assert r.status_code == 200
    colors = r.json()["rec_bd_colors"]
    assert len(set(colors)) == 8  # no duplicates in extended palette for small counts
