"""Spike E — Scenario 3 sanity check: ring wrap borrow.

Validates whether the progressive-demand approach naturally produces
SPEC §11-compliant ordering when Port 1 requires ring-wrap borrow
(across the M4↔M1 bridge B_4_1).

Throwaway prototype — do not modify production code, do not commit.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

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

# Scenario 3:
# - Port 1 (M1.O1) arriving at 350 kW — triggers ring wrap into MCU 4
# - Port 3 (M2.O1) already serving 200 kW (BD 2 anchor + extension; static)
# - Port 5 (M3.O1) already serving 200 kW (BD 3 anchor + extension; static)
INITIAL_PORTS = [
    CarPortInput(port_id=1, max_required=0, present=0, target=350, priority=1),
    CarPortInput(port_id=2, max_required=0, present=0, target=0, priority=5),
    CarPortInput(port_id=3, max_required=200, present=200, target=200, priority=2),
    CarPortInput(port_id=4, max_required=0, present=0, target=0, priority=6),
    CarPortInput(port_id=5, max_required=200, present=200, target=200, priority=3),
    CarPortInput(port_id=6, max_required=0, present=0, target=0, priority=7),
    CarPortInput(port_id=7, max_required=0, present=0, target=0, priority=4),
    CarPortInput(port_id=8, max_required=0, present=0, target=0, priority=8),
]


def progressive_demand(initial, step_index: int):
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
            print("[ABORT] step > 30")
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
    print("=== Spike E Scenario 3: Ring Wrap Borrow ===")
    print(f"Scenario: Port 1 → 350 kW (ring wrap into MCU 4)")
    active_initial = [(p.port_id, p.present) for p in INITIAL_PORTS if p.present > 0 or p.target > 0]
    active_target = [(p.port_id, p.target) for p in INITIAL_PORTS if p.present > 0 or p.target > 0]
    print(f"Initial demands: {active_initial}")
    print(f"Target  demands: {active_target}")
    print()

    snapshots, timings = asyncio.run(run_spike())

    for i, (step, ports, snap) in enumerate(snapshots):
        active = [(p.port_id, p.max_required) for p in ports if p.max_required > 0]
        print(f"--- Snapshot {i} (step={step}, time={timings[i]:.1f}ms) ---")
        print(f"  Active demands: {active}")
        print(f"  total_power_kw: {snap.total_power_kw}")
        closed_relays = sorted([r.id for r in snap.relays if r.state == "Closed"])
        print(f"  Closed relays: {closed_relays}")
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
    print(f"Unique snapshots: {len(unique_snapshots)}")
    print(f"Total elapsed: {sum(timings):.0f} ms")
    if timings:
        sorted_t = sorted(timings)
        p95_idx = min(len(sorted_t) - 1, int(len(sorted_t) * 0.95))
        print(f"Avg per create: {sum(timings)/len(timings):.1f} ms")
        print(f"P95 per create: {sorted_t[p95_idx]:.1f} ms")
    print()

    final_snap = snapshots[-1][2]
    print("=== Final State Check ===")
    p1_car = next((c for c in final_snap.cars if c.port_id == 1), None)
    p1_relay = next((r for r in final_snap.relays if r.id == "M1.O1"), None)
    bridges = [(r.id, r.state) for r in final_snap.relays if r.kind == "bridge"]
    print(f"Port 1 allocated_kw: {p1_car.allocated_kw if p1_car else 'N/A'} (expected: 350)")
    print(f"M1.O1 state: {p1_relay.state if p1_relay else 'N/A'} (expected: Closed)")
    print(f"All bridges: {bridges}")
    print(f"total_power_kw: {final_snap.total_power_kw}")

    # ── SPEC §11 invariant walk ───────────────────────────────────────
    print()
    print("=== SPEC §11 Invariant Walk ===")
    # Track at which step M1.O1 closes and B_4_1 closes
    m1_o1_close_step = None
    bridge_close_steps = {}
    intergroup_close_steps = {}  # by id
    for i, (_, _, snap) in enumerate(snapshots):
        if i == 0:
            continue
        diff = relay_diff(snapshots[i - 1][2], snap)
        for rid, frm, to in diff:
            if to == "Closed":
                if rid == "M1.O1" and m1_o1_close_step is None:
                    m1_o1_close_step = i
                if rid.startswith("B_") and rid not in bridge_close_steps:
                    bridge_close_steps[rid] = i
                if rid.startswith("M") and ".R" in rid and rid not in intergroup_close_steps:
                    intergroup_close_steps[rid] = i

    print(f"M1.O1 closed at step: {m1_o1_close_step}")
    print(f"Bridge close steps: {bridge_close_steps}")
    print(f"Inter-group close steps: {intergroup_close_steps}")
    if m1_o1_close_step is not None:
        # Find allocated_kw at the step BEFORE M1.O1 closed
        prev_snap = snapshots[m1_o1_close_step - 1][2]
        prev_p1 = next((c for c in prev_snap.cars if c.port_id == 1), None)
        cur_snap = snapshots[m1_o1_close_step][2]
        cur_p1 = next((c for c in cur_snap.cars if c.port_id == 1), None)
        print(f"  P1 alloc one-step-before close: {prev_p1.allocated_kw if prev_p1 else 'N/A'}")
        print(f"  P1 alloc at close: {cur_p1.allocated_kw if cur_p1 else 'N/A'}")


if __name__ == "__main__":
    main()
