"""S2.1 — happy-path snapshot tests for dynamic ``rec_bd_count``.

These tests verify that the ``WebSessionEngine`` ``rec_bd_count`` lock
removed in S2.1 lets layouts with N ∈ {1, 2, 3, 5, 6} round-trip through
``POST /api/v1/snapshot/compute`` without errors and produce snapshots
with the right shape (1..12 REC BDs each carrying 2 car ports).

S2.1 unlocks **count only**; per-REC-BD ``module_powers`` is still locked
to ``[50, 75, 75, 50]`` here because the simulation core hasn't grown
support for arbitrary group powers yet (FR-11 dynamic shape lands in
S2.2). All test configs therefore use the default power list.

Coverage scoped to zero-demand baselines (no settle / no borrow) so the
sync ``compute_snapshot`` path is exercised end-to-end without depending
on async convergence. Higher-demand variants land alongside FR-11 work.
"""
from __future__ import annotations

from typing import List

import pytest
from fastapi.testclient import TestClient


def _cfg(n: int) -> dict:
    return {
        "rec_bd_count": n,
        "rec_bds": [
            {"id": i + 1, "module_powers": [50, 75, 75, 50]}
            for i in range(n)
        ],
    }


def _ports_zero(n: int) -> List[dict]:
    return [
        {"port_id": pid, "max_required": 0, "present": 0, "target": 0, "priority": None}
        for pid in range(1, 2 * n + 1)
    ]


def _snapshot(client: TestClient, cfg: dict, ports: List[dict]) -> dict:
    r = client.post(
        "/api/v1/snapshot/compute",
        json={"system_config": cfg, "car_ports": ports},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _assert_idle_shape(snap: dict, n: int) -> None:
    assert len(snap["rec_bds"]) == n
    assert all(bd["status"] == "Idle" for bd in snap["rec_bds"])
    assert all(bd["power_kw"] == 0 for bd in snap["rec_bds"])

    assert len(snap["cars"]) == 2 * n
    assert all(c["status"] == "Inactive" for c in snap["cars"])
    assert all(c["allocated_kw"] == 0 for c in snap["cars"])

    assert snap["total_power_kw"] == 0
    assert snap["total_requested_kw"] == 0
    assert all(r["state"] == "Open" for r in snap["relays"])


# ---------------------------------------------------------------------------
# N = 1 — single MCU, no bridges (SPEC §2.2 N==1 case)
# ---------------------------------------------------------------------------

def test_snapshot_n1_single_mcu_no_bridge(client: TestClient):
    snap = _snapshot(client, _cfg(1), _ports_zero(1))
    _assert_idle_shape(snap, 1)
    assert not any(r["kind"] == "bridge" for r in snap["relays"])


# ---------------------------------------------------------------------------
# N = 2 — linear topology, exactly one bridge (SPEC §2.2 N==2 case)
# ---------------------------------------------------------------------------

def test_snapshot_n2_linear_one_bridge(client: TestClient):
    snap = _snapshot(client, _cfg(2), _ports_zero(2))
    _assert_idle_shape(snap, 2)
    bridges = [r for r in snap["relays"] if r["kind"] == "bridge"]
    assert len(bridges) == 1
    assert bridges[0]["id"] == "B_1_2"


# ---------------------------------------------------------------------------
# N = 3 — smallest ring (SPEC §2.2 N>=3 ring case)
# ---------------------------------------------------------------------------

def test_snapshot_n3_smallest_ring(client: TestClient):
    snap = _snapshot(client, _cfg(3), _ports_zero(3))
    _assert_idle_shape(snap, 3)
    bridges = sorted(r["id"] for r in snap["relays"] if r["kind"] == "bridge")
    assert bridges == ["B_1_2", "B_2_3", "B_3_1"]


# ---------------------------------------------------------------------------
# N = 5 — odd ring (mid-range)
# ---------------------------------------------------------------------------

def test_snapshot_n5_ring(client: TestClient):
    snap = _snapshot(client, _cfg(5), _ports_zero(5))
    _assert_idle_shape(snap, 5)
    bridges = sorted(r["id"] for r in snap["relays"] if r["kind"] == "bridge")
    assert bridges == sorted(["B_1_2", "B_2_3", "B_3_4", "B_4_5", "B_5_1"])


# ---------------------------------------------------------------------------
# N = 6 — even ring (mid-range)
# ---------------------------------------------------------------------------

def test_snapshot_n6_ring(client: TestClient):
    snap = _snapshot(client, _cfg(6), _ports_zero(6))
    _assert_idle_shape(snap, 6)
    bridges = sorted(r["id"] for r in snap["relays"] if r["kind"] == "bridge")
    assert bridges == sorted(["B_1_2", "B_2_3", "B_3_4", "B_4_5", "B_5_6", "B_6_1"])
