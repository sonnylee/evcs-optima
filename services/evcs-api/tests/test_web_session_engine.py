"""Tests for ``WebSessionEngine`` — Step F09.1.

These exercise the rebuild-engine adapter directly (no FastAPI client). They
verify the Sprint 1 envelope (4 MCU × [50,75,75,50]), basic snapshot
correctness, and SPEC §11 invariants on the produced ``VisualSnapshot``.
"""
from __future__ import annotations

import re
from typing import List, Tuple

import pytest

from app.schemas.car_port import CarPortInput
from app.schemas.config import SystemConfig
from app.schemas.snapshot import VisualSnapshot
from app.services.web_session_engine import WebSessionEngine


# ── Fixture-style builders (mirror tests/test_snapshot.py) ─────────────────

def _cfg(n: int = 4, module_powers: List[int] | None = None) -> SystemConfig:
    mp = module_powers if module_powers is not None else [50, 75, 75, 50]
    return SystemConfig.model_validate(
        {
            "rec_bd_count": n,
            "rec_bds": [{"id": i + 1, "module_powers": list(mp)} for i in range(n)],
        }
    )


def _ports(specs: List[Tuple[int, int, int | None]]) -> List[CarPortInput]:
    """specs: list of (port_id, max_required, priority_or_None)."""
    return [
        CarPortInput.model_validate(
            {
                "port_id": pid,
                "max_required": mr,
                "present": 0,
                "target": 0,
                "priority": pr,
            }
        )
        for pid, mr, pr in specs
    ]


def _all_zero_ports(rec_bd_count: int = 4) -> List[CarPortInput]:
    return _ports([(pid, 0, None) for pid in range(1, rec_bd_count * 2 + 1)])


def _set(specs: List[Tuple[int, int, int | None]], rec_bd_count: int = 4) -> List[CarPortInput]:
    """Helper: build a full 2N-port list, override the entries given in `specs`."""
    out = {pid: (pid, 0, None) for pid in range(1, rec_bd_count * 2 + 1)}
    for pid, mr, pr in specs:
        out[pid] = (pid, mr, pr)
    return _ports(list(out.values()))


def _relay(snap: VisualSnapshot, rid: str):
    return next((r for r in snap.relays if r.id == rid), None)


def _output_relay_for(snap: VisualSnapshot, port_id: int):
    rec_bd_id = (port_id - 1) // 2 + 1
    local_idx = (port_id - 1) % 2 + 1
    return _relay(snap, f"M{rec_bd_id}.O{local_idx}")


# ── Shared invariant assertions (call from every successful test) ────────

_RELAY_ID_RE = re.compile(r"^(M\d+\.O\d+|M\d+\.R\d+|B_\d+_\d+)$")


def _assert_snapshot_invariants(snap: VisualSnapshot, system: SystemConfig) -> None:
    # 1. No pack double-owned.
    keys = [(p.rec_bd_id, p.pack_index) for p in snap.packs]
    assert len(keys) == len(set(keys)), "Pack list contains duplicates"

    # 2. Every CLOSED output relay has allocated_kw >= 125 (SPEC §11).
    cars_by_port = {c.port_id: c for c in snap.cars}
    for relay in snap.relays:
        if relay.kind == "output" and relay.state == "Closed":
            car = cars_by_port[relay.owner_port_id]
            assert car.allocated_kw >= 125, (
                f"output relay {relay.id} closed with allocated_kw={car.allocated_kw} "
                f"< 125 (SPEC §11)"
            )

    # 3. Σ allocated_kw <= system.total_capacity_kw.
    total = sum(c.allocated_kw for c in snap.cars)
    assert total <= system.total_capacity_kw, (
        f"Σ allocated_kw={total} > total_capacity_kw={system.total_capacity_kw}"
    )

    # 4. Every pack.rec_bd_id ∈ 1..rec_bd_count.
    for p in snap.packs:
        assert 1 <= p.rec_bd_id <= system.rec_bd_count, p

    # 5. Relay id format matches.
    for r in snap.relays:
        assert _RELAY_ID_RE.match(r.id), f"unexpected relay id format: {r.id}"


# ── 8 test cases ──────────────────────────────────────────────────────────

def test_empty_demand():
    system = _cfg(4)
    eng = WebSessionEngine(system, _all_zero_ports(4))
    snap = eng.to_visual_snapshot()

    assert snap.total_power_kw == 0
    assert snap.total_requested_kw == 0
    for r in snap.relays:
        if r.kind == "output":
            assert r.state == "Open"
    for c in snap.cars:
        assert c.status == "Inactive"
        assert c.allocated_kw == 0
    _assert_snapshot_invariants(snap, system)


def test_single_port_125kw():
    system = _cfg(4)
    eng = WebSessionEngine(system, _set([(1, 125, None)]))
    snap = eng.to_visual_snapshot()

    p1_relay = _output_relay_for(snap, 1)
    assert p1_relay.state == "Closed"
    car_p1 = next(c for c in snap.cars if c.port_id == 1)
    assert car_p1.allocated_kw >= 125
    # ports 2..8 inactive
    for port_id in range(2, 9):
        r = _output_relay_for(snap, port_id)
        assert r.state == "Open", f"port {port_id} relay should be Open"
    _assert_snapshot_invariants(snap, system)


def test_single_port_250kw():
    system = _cfg(4)
    eng = WebSessionEngine(system, _set([(1, 250, None)]))
    snap = eng.to_visual_snapshot()

    p1_owned = [p for p in snap.packs if p.owner_port_id == 1]
    # 250 kW = 10 packs (full REC BD 1, anchor + 3 more groups).
    assert len(p1_owned) == 10
    assert {p.rec_bd_id for p in p1_owned} == {1}, "should be local-only at 250 kW"
    # At least one inter-group relay closed (the borrow extends across groups).
    inter = [r for r in snap.relays if r.kind == "inter_group" and r.rec_bd_id == 1]
    assert any(r.state == "Closed" for r in inter), "no inter-group relay closed"
    _assert_snapshot_invariants(snap, system)


def test_two_ports_same_recbd():
    system = _cfg(4)
    eng = WebSessionEngine(system, _set([(1, 125, None), (2, 125, None)]))
    snap = eng.to_visual_snapshot()

    assert _output_relay_for(snap, 1).state == "Closed"
    assert _output_relay_for(snap, 2).state == "Closed"

    # No double-ownership and REC BD 1 fully utilized.
    keys = [(p.rec_bd_id, p.pack_index) for p in snap.packs if p.in_use]
    assert len(keys) == len(set(keys))
    rec_bd_1 = next(bd for bd in snap.rec_bds if bd.id == 1)
    assert rec_bd_1.used_packs >= 10
    _assert_snapshot_invariants(snap, system)


def test_two_ports_cross_mcu():
    system = _cfg(4)
    eng = WebSessionEngine(system, _set([(1, 350, None)]))
    snap = eng.to_visual_snapshot()

    # 350 kW > 250 (REC BD 1 capacity) so port 1 must borrow from a neighbor.
    bridges = [r for r in snap.relays if r.kind == "bridge"]
    assert any(r.state == "Closed" for r in bridges), (
        "expected at least one bridge relay Closed for cross-MCU borrow"
    )
    _assert_snapshot_invariants(snap, system)


def test_full_8_ports_125kw():
    system = _cfg(4)
    eng = WebSessionEngine(system, _ports([(pid, 125, None) for pid in range(1, 9)]))
    snap = eng.to_visual_snapshot()

    for port_id in range(1, 9):
        r = _output_relay_for(snap, port_id)
        assert r.state == "Closed", f"port {port_id} should be Closed"
    assert snap.total_power_kw == 1000
    bridges = [r for r in snap.relays if r.kind == "bridge"]
    assert all(r.state == "Open" for r in bridges), (
        "no bridge should close — local capacity is sufficient"
    )
    _assert_snapshot_invariants(snap, system)


def test_invalid_config_3mcu():
    system = _cfg(3)
    with pytest.raises(ValueError, match="Sprint 1"):
        WebSessionEngine(system, _ports([(1, 0, None), (2, 0, None), (3, 0, None), (4, 0, None), (5, 0, None), (6, 0, None)]))


def test_invalid_config_nonstd_module_powers():
    system = _cfg(4, module_powers=[50, 50, 100, 50])
    with pytest.raises(ValueError, match="Sprint 1"):
        WebSessionEngine(system, _all_zero_ports(4))
