"""Spike E: Demand Progression Prototype.

Validate whether a progressive ``max_required`` sequence (Present → Target in
``STEP_KW`` increments) fed through ``WebSessionEngine.create()`` produces a
snapshot sequence that mirrors the SPEC §11-ordered step narrative for
DEMO_FR14_SCENARIO Scenario 2.

Throwaway prototype — do not modify production code, do not commit.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

# Ensure both project root and services/evcs-api are importable regardless of
# the invocation cwd.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "services", "evcs-api"))

from app.constants import STEP_KW  # noqa: E402
from app.schemas.car_port import CarPortInput  # noqa: E402
from app.schemas.config import RecBdConfig, SystemConfig  # noqa: E402
from app.services.web_session_engine import WebSessionEngine  # noqa: E402


SYSTEM = SystemConfig(
    rec_bd_count=4,
    rec_bds=[
        RecBdConfig(id=i + 1, module_powers=[50, 75, 75, 50]) for i in range(4)
    ],
)

INITIAL_PORTS = [
    CarPortInput(port_id=1, max_required=300, present=300, target=0, priority=1),
    CarPortInput(port_id=2, max_required=0, present=0, target=0, priority=5),
    CarPortInput(port_id=3, max_required=150, present=150, target=0, priority=2),
    CarPortInput(port_id=4, max_required=0, present=0, target=0, priority=6),
    CarPortInput(port_id=5, max_required=250, present=50, target=250, priority=3),
    CarPortInput(port_id=6, max_required=0, present=0, target=0, priority=7),
    CarPortInput(port_id=7, max_required=200, present=50, target=200, priority=4),
    CarPortInput(port_id=8, max_required=0, present=0, target=0, priority=8),
]


def progressive_demand(initial, step_index: int):
    """Return new CarPortInput list with max_required advanced by step_index × STEP_KW."""
    result = []
    for cp in initial:
        delta = step_index * STEP_KW
        if cp.target > cp.present:
            direction = 1
        elif cp.target < cp.present:
            direction = -1
        else:
            direction = 0
        candidate = cp.present + direction * delta
        lo = min(cp.present, cp.target)
        hi = max(cp.present, cp.target)
        new_max = max(lo, min(hi, candidate))
        result.append(cp.model_copy(update={"max_required": new_max}))
    return result


def is_target_reached(ports) -> bool:
    return all(cp.max_required == cp.target for cp in ports)


async def run_spike():
    snapshots = []
    timings = []
    step = 0
    while True:
        ports_at_step = progressive_demand(INITIAL_PORTS, step)
        t0 = time.perf_counter()
        engine = await WebSessionEngine.create(SYSTEM, ports_at_step)
        snap = engine.to_visual_snapshot()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        snapshots.append((step, ports_at_step, snap))
        timings.append(elapsed_ms)
        if is_target_reached(ports_at_step):
            break
        step += 1
        if step > 30:
            print("[ABORT] step > 30, something wrong")
            break
    return snapshots, timings


def relay_diff(snap_a, snap_b):
    a_by_id = {r.id: r for r in snap_a.relays}
    diffs = []
    for r in snap_b.relays:
        prev = a_by_id.get(r.id)
        if prev and prev.state != r.state:
            diffs.append((r.id, prev.state, r.state))
    return diffs


def main():
    print("=== Spike E: Demand Progression Prototype ===")
    print("Scenario: Demo 場景 2 (4 BD × [50,75,75,50])")
    active_initial = [(p.port_id, p.present) for p in INITIAL_PORTS if p.present > 0 or p.target > 0]
    active_target = [(p.port_id, p.target) for p in INITIAL_PORTS if p.present > 0 or p.target > 0]
    print(f"Initial demands: {active_initial}")
    print(f"Target  demands: {active_target}")
    print()

    snapshots, timings = asyncio.run(run_spike())

    # === Step Z.1 — Power Breakdown debug (throwaway) ==================
    snap0 = snapshots[0][2]
    print("\n=== Step 0 Power Breakdown ===")
    print(f"snap.total_power_kw    = {snap0.total_power_kw}")
    print(f"snap.total_requested_kw = {snap0.total_requested_kw}")
    print("Per-port car.allocated_kw:")
    for c in snap0.cars:
        if c.allocated_kw > 0 or c.max_required > 0:
            print(
                f"  Port {c.port_id}: allocated={c.allocated_kw}, "
                f"max_required={c.max_required}, status={c.status}"
            )
    sum_alloc = sum(c.allocated_kw for c in snap0.cars)
    print(f"  Sum(car.allocated_kw) = {sum_alloc}")
    print("Per-BD bd.power_kw:")
    for bd in snap0.rec_bds:
        if bd.power_kw > 0:
            print(
                f"  BD {bd.id}: power={bd.power_kw}, "
                f"used_packs={bd.used_packs}/{bd.total_packs}"
            )
    sum_bd = sum(bd.power_kw for bd in snap0.rec_bds)
    print(f"  Sum(bd.power_kw) = {sum_bd}")
    print("Pack ownership count by port:")
    pack_count: dict = {}
    for p in snap0.packs:
        if p.owner_port_id:
            pack_count[p.owner_port_id] = pack_count.get(p.owner_port_id, 0) + 1
    for pid, cnt in sorted(pack_count.items()):
        print(f"  Port {pid}: {cnt} packs × 25 kW = {cnt * 25} kW")
    print()

    for i, (step, ports, snap) in enumerate(snapshots):
        active = [(p.port_id, p.max_required) for p in ports if p.max_required > 0]
        print(f"--- Snapshot {i} (step={step}, time={timings[i]:.1f}ms) ---")
        print(f"  Active demands: {active}")
        print(f"  total_power_kw: {snap.total_power_kw}")
        closed_relays = sorted([r.id for r in snap.relays if r.state == "Closed"])
        print(f"  Closed relays:  {closed_relays}")
        if i > 0:
            diff = relay_diff(snapshots[i - 1][2], snap)
            if diff:
                print(f"  Diff from prev: {diff}")
            else:
                print("  Diff from prev: (no relay change)")
        print()

    unique_snapshots = []
    prev_relays = None
    for _, _, snap in snapshots:
        rs = tuple(sorted([(r.id, r.state) for r in snap.relays]))
        if rs != prev_relays:
            unique_snapshots.append(snap)
            prev_relays = rs

    print("=== Summary ===")
    print(f"Total snapshots: {len(snapshots)}")
    print(f"Unique snapshots (after dedup on relay state): {len(unique_snapshots)}")
    print(f"Total elapsed: {sum(timings):.0f} ms")
    if timings:
        print(f"Avg per create: {sum(timings) / len(timings):.1f} ms")
        sorted_t = sorted(timings)
        p95_idx = min(len(sorted_t) - 1, int(len(sorted_t) * 0.95))
        print(f"P95 per create: {sorted_t[p95_idx]:.1f} ms")
    print()

    final_snap = snapshots[-1][2]
    print("=== Final State Check ===")
    print(f"Final total_power_kw: {final_snap.total_power_kw} (expected: 450 = Port5 250 + Port7 200)")
    for relay_id, label, expected in [
        ("M1.O1", "Port 1", "Open"),
        ("M2.O1", "Port 3", "Open"),
        ("M3.O1", "Port 5", "Closed"),
        ("M4.O1", "Port 7", "Closed"),
    ]:
        r = next((rr for rr in final_snap.relays if rr.id == relay_id), None)
        actual = r.state if r else "N/A"
        ok = "✓" if actual == expected else "✗"
        print(f"  {relay_id} ({label}, should be {expected}): {actual} {ok}")


if __name__ == "__main__":
    main()
