"""Topology preview tests — FR-01 + FR-10 + FR-11."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _cfg(n: int) -> dict:
    return {
        "rec_bd_count": n,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]}
            for i in range(n)
        ],
    }


def test_preview_single_rec_bd_has_no_bridges(client: TestClient):
    body = client.post(
        "/api/v1/topology/preview",
        json={"system_config": _cfg(1)},
    ).json()
    assert body["rec_bd_count"] == 1
    assert body["car_port_count"] == 2
    assert body["total_capacity_kw"] == 250
    assert body["bridge_relay_ids"] == []  # SPEC §2.2: N=1 → no bridges


def test_preview_two_rec_bd_linear(client: TestClient):
    body = client.post(
        "/api/v1/topology/preview",
        json={"system_config": _cfg(2)},
    ).json()
    assert body["bridge_relay_ids"] == ["B_1_2"]  # single linear bridge


def test_preview_four_rec_bd_ring(client: TestClient):
    body = client.post(
        "/api/v1/topology/preview",
        json={"system_config": _cfg(4)},
    ).json()
    # SPEC §2.2: N>=3 ring closes head↔tail.
    assert body["bridge_relay_ids"] == ["B_1_2", "B_2_3", "B_3_4", "B_4_1"]
    assert body["car_port_count"] == 8

    bd1 = body["rec_bds"][0]
    # 4-module REC BD → R2, R3, R4 inter-group relays + M1.O1, M1.O2 output relays.
    assert bd1["inter_group_relay_ids"] == ["M1.R2", "M1.R3", "M1.R4"]
    assert bd1["output_relay_ids"] == ["M1.O1", "M1.O2"]
    assert bd1["car_port_ids"] == [1, 2]


def test_preview_pack_slicing_fr11(client: TestClient):
    """FR-11: 50→2 packs, 75→3, 100→4."""
    cfg = {
        "rec_bd_count": 1,
        "rec_bds": [{"id": 1, "module_powers": [50, 75, 100, 75]}],  # 300 kW total
    }
    body = client.post(
        "/api/v1/topology/preview",
        json={"system_config": cfg},
    ).json()
    bd = body["rec_bds"][0]
    assert bd["total_capacity_kw"] == 300
    assert bd["pack_count"] == 12  # 2+3+4+3
    assert [m["pack_count"] for m in bd["modules"]] == [2, 3, 4, 3]
    # Pack indices should partition [0..11] contiguously with no gaps.
    flat = [i for m in bd["modules"] for i in m["pack_indices"]]
    assert flat == list(range(12))


def test_preview_palette_cycle_repeats_every_four(client: TestClient):
    body = client.post(
        "/api/v1/topology/preview",
        json={"system_config": _cfg(6), "cycle_palette": True},
    ).json()
    colors = [bd["color"] for bd in body["rec_bds"]]
    assert colors[0] == colors[4]  # FR-10: 4-color cycle
    assert colors[1] == colors[5]
