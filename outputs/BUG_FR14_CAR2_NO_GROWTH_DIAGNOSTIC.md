# BUG_FR14_CAR2_NO_GROWTH — Diagnostic Spike Report

**Date**: 2026-05-12
**Branch / HEAD**: `main` @ `0d55c5f` (S2.8 — Sprint 2 doc finalization + central index)
**Scope**: read-only diagnostic; no production code, test, or SPEC changes

---

## §1 Baseline

| Check | Result |
|---|---|
| `services/evcs-api/tests -q` | **92 passed, 1 xfailed, 2 deselected** ✓ |
| `tests/ -q` (simulation) | **241 passed** ✓ |
| `web/evcs-ui` `npx tsc --noEmit` | **0 errors** ✓ |

Baseline green — spike proceeded.

---

## §2 Reproduce result

Two scripts were run (now deleted): `repro.py` for the raw `WebSessionEngine` final snapshot (FR-09 path), and `repro_fr14.py` for the full FR-14 `generate_control_steps` flow.

### §2.1 `WebSessionEngine.create(mode='target')` final snapshot (source of truth)

**Car allocations**:

| Port | Pri | max_req | alloc | Status |
|---|---:|---:|---:|---|
| 1 | 3 | 300 | **325** | Active |
| 2 | 2 | 200 | **125** | Active |
| 3 | 1 | 100 | **125** | Active |

**BD1 pack ownership** (all 10 packs owned, used=10/10):

```
pack[0..1]  owner=1   (Port 1 anchor G0, 50 kW)
pack[2..4]  owner=1   (Port 1 expanded to G1, 75 kW)
pack[5..7]  owner=2   (Port 2 expanded to G2, 75 kW)
pack[8..9]  owner=2   (Port 2 anchor G3, 50 kW)
```

**BD4** packs 2..9 owned by Port 1 (200 kW cross-BD borrow via `B_4_1` bridge).

**MCU0 intervals**: `out0=[-3, 1]` (Port 1, wraps left to MCU3); `out1=[2, 3]` (Port 2, local).

→ **The simulation core / `WebSessionEngine` settle is CORRECT.** Car 2 actually receives 125 kW, not 50 kW. This contradicts the bug-report screenshot.

### §2.2 `generate_control_steps` (FR-14) — reproduces the bug

`total_steps = 5`. Step descriptions and final-step car allocations:

| Step | Description | Port 1 alloc | Port 2 alloc | Port 3 alloc |
|---|---|---:|---:|---:|
| (initial) | Present state | 50 | 50 | 125 |
| 1 | Close M1.R2 (Port 1 expanding to 125 kW) | 125 | 50 | 125 |
| 2 | Close M1.R4 (Port 1 expanding to 125 kW) | 125 | 50 | 125 |
| 3 | Close M4.R3 (Port 1 expanding to 125 kW) | 125 | 50 | 125 |
| 4 | Close M4.R4 (Port 1 expanding to 125 kW) | 125 | 50 | 125 |
| 5 | Close B_4_1 (Port 1 expanding to 325 kW) | 325 | **50** | 125 |

**Last-step BD1 pack ownership** (used=7/10 — matches the bug screenshot exactly):

```
pack[0..1]  owner=1
pack[2..4]  owner=1     (G1, 75 kW — correctly transferred)
pack[5..7]  owner=None  ← THE BUG: G2 (75 kW) shown idle in player
pack[8..9]  owner=2
```

→ **The stitched FR-14 last-step snapshot DIVERGES from `final_state`.** This is DP-1: bug is **not** in `mcu_control`; it is in `step_planner._stitch_snapshot` / `_resolve_pack_owner`.

---

## §3 Settle trace observations

- **Port 1 anchor**: BD1 G0 (global group idx 0). `output_min_guarantee_kw([50,75,75,50], 0) = 50+75 = 125 kW`.
- **Port 2 anchor**: BD1 G3 (global group idx 3). `output_min_guarantee_kw([50,75,75,50], 1) = 50+75 = 125 kW`.
- **`handle_vehicle_arrival` initial claim**: Port 1 claims `[G0, G1]`; Port 2 claims `[G2, G3]` (`mcu_control.py:511-547`). Both ports arrive at the SPEC §11 minimum guarantee in the engagement phase — confirmed by stdout: `Port 2: user_max=200 kW, engagement_avail=125 kW, output_relay=CLOSED`.
- **Settle loop**: with target=200 and `pre_available=125`, `_tick_return_condition` requires `(125 − 200) ≥ 75` which is False, so Port 2 never returns. `_tick_borrow_condition` requires `present ≈ available`; with no further demand pressure beyond 125 + flat-curve plateau, Port 2 holds steady at G2+G3. Final web-path snapshot shows exactly this.

The settle algorithm is **working as designed**. Car 2's 125 kW result is correct from `MCUControl`.

### §3.1 Anchor adjacency (point 4)

Port 1 (G0, idx 0) and Port 2 (G3, idx 3) are at **opposite ends** of BD1, NOT adjacent. R3 (G1↔G2) is the only inter-group relay between their territories; it stays OPEN in steady state because Port 1's interval `[-3, 1]` (wrapping left) and Port 2's `[2, 3]` (local) are disjoint and contiguous on their own sides. This is correct.

### §3.2 Priority placement observation (out of scope but noted)

`CLAUDE.md` says "Priority (FR-16) is fed into `WebSessionEngine`'s placement order, replacing the default top-down Car-ID allocation." However, `web_session_engine.py:163-193` (`_build_simulation_config`) builds `placements` by iterating `self._car_ports` in their incoming list order with no `sort(key=priority)`. For this scenario the three cars anchor at non-overlapping groups (G0 / G3 / G4), so priority order does not affect the outcome. Flagging only — does not contribute to this bug.

---

## §4 Root cause hypothesis (Bug A)

**Main hypothesis**: Bug A is a **downstream consequence of Bug B**.

`step_planner._resolve_pack_owner` (line 474-546) decides per-pack ownership in stitched snapshots by looking up a "gating relay set" computed from **flips attributed to the candidate port**:

```python
port_flips = [f for f in flips_by_id.values() if f.port == candidate_port]
```

If a relay flip is mis-attributed to the wrong port, the correct port's `port_flips` is missing it. Then for a same-BD pack claim:

```python
if pack_bd == anchor_bd:
    # gating = inter_group relays in this BD that belong to this port,
    # connecting anchor_group ↔ pack_group
```

returns an empty `gating` set → falls through to the "no gating" branch (line 530-538):

```python
out_id = _output_relay_id(candidate_port)   # e.g. M1.O2
if is_claiming:
    return fp.owner_port_id if out_id in applied else ip.owner_port_id
```

For Port 2 expanding to G2 (claiming packs 5-7):
- Port 2's output relay `M1.O2` was already Closed in `initial_state` (present=50 was anchored at G3) and stays Closed in `final_state`. So `M1.O2` **never appears as a flip** and is never in `applied`.
- Therefore `_resolve_pack_owner` returns `ip.owner_port_id = None` at every step — including the last.

**Evidence**:

| Relay flip | Correct attribution | Actual `_attribute_flip` result | `_adjacent_pack_owners` output |
|---|---|---|---|
| M1.R2 (BD1 G0↔G1) | Port 1 (expansion) | Port 1 | `[1, 2]` — coincidentally correct via `min()` |
| **M1.R4 (BD1 G2↔G3)** | **Port 2 (expansion from G3 anchor)** | **Port 1** ← **mis-attribution** | `[1, 2]` |
| M4.R3 (BD4 G1↔G2) | Port 1 (cross-BD borrow) | Port 1 | `[1]` |
| M4.R4 (BD4 G2↔G3) | Port 1 (cross-BD borrow) | Port 1 | `[1]` |
| B_4_1 (BD4↔BD1) | Port 1 (cross-BD bridge) | Port 1 | `[1, 2]` — coincidentally correct via `min()` |

Because M1.R4 is mis-attributed to Port 1, Port 2's `port_flips` is empty for this BD; with no gating relay in `applied`, packs 5-7 never transition to `owner=2` in any stitched snapshot — including the last step where the bug visibly manifests as `Car 2 = 50 kW` and `BD1 used = 7/10`.

**Code references**: `services/evcs-api/app/adapters/step_planner.py:163-200` (`_attribute_flip`); `203-232` (`_adjacent_pack_owners` — see §5); `474-546` (`_resolve_pack_owner`); `501` (the `port_flips` filter that depends on attribution).

**No alternative hypothesis matches the evidence** — direct call to `_resolve_pack_owner` after Bug B is fixed would resolve the bug because gating set becomes `{M1.R4}`, R4 is in `applied` from step 2 onward, and Port 2 would correctly claim packs 5-7.

---

## §5 Bug B verification

**`_adjacent_pack_owners` group filter missing — CONFIRMED.**

`step_planner.py:203-224` for `kind == "inter_group"`:

```python
left_g = r_num - 2          # line 214 — computed
right_g = r_num - 1          # line 215 — computed
owners: List[int] = []
for p in snap.packs:
    if p.rec_bd_id != bd_id or p.owner_port_id is None:
        continue
    # Find the group index for this pack
    # (rough: rely on ordering — pack_index sorted)   ← admits incomplete
    owners.append(p.owner_port_id)                    ← unconditional append
return list(dict.fromkeys(owners))
```

`left_g` and `right_g` are computed but **never referenced**. The for loop appends every pack owner in the BD, regardless of which group the pack sits in. Then `_attribute_flip:200` returns `min(owners)` — always the lowest port_id that owns ANYTHING in this BD.

For BD1 (homed by Port 1 + Port 2), `min([1, 2]) = 1` always, so every BD1 inter-group flip attributes to Port 1. This is exactly the failure mode observed.

**Other attribution paths**: the only earlier escape is the "departing port" tie-break at line 197-199:
```python
departing = [p for p in owners if ... == _Phase.DEPARTURE]
if departing:
    return departing[0]
```
In this scenario all 3 ports are in `_Phase.INCREASE` (present>0, target>present), so the departing path is empty — `min(owners)` runs unconditionally.

For bridges (line 225-231), the same shape problem applies, but bridges genuinely span two BDs, so listing every owner in both BDs is closer to the intent (the relay really does connect to whichever port spans either side). Not actively wrong in this scenario; flag only.

---

## §6 CLI vs web path

Not run. Rationale: §2.1 showed the web-path `WebSessionEngine` final snapshot already gives the **correct** Car 2 = 125 kW. The bug only manifests inside `step_planner` stitching (FR-14 player). CLI `SimulationEngine.run()` shares the same `mcu_control` and would produce the same correct settled state — there's nothing to compare. If we later doubt the FR-09 path, this is worth re-running, but for FR-14 stitching it adds no information.

---

## §7 Suggested next steps

### Bug A fix direction (strategy only — no code)

**Two-stage fix, ordered**:

1. **Fix Bug B first** (`_adjacent_pack_owners` for `inter_group`). Restore the `left_g`/`right_g` filter: an inter-group relay R(k+2) connects local groups `k` and `k+1`; only packs whose group index is `k` or `k+1` are adjacent. Use `_pack_to_group(system, bd_id, pack.pack_index)` (already exists in `step_planner.py:122`) to map pack → group, then keep only packs whose group ∈ {left_g, right_g}. This narrows the owners list to the actual ports touching this relay.

2. **Verify Bug A drops out**. After fix #1, M1.R4 owners filter to `[2]` (only Port 2 owns G3, G2 is None in initial → only Port 2 spans both sides in final). `_attribute_flip` returns Port 2. `_resolve_pack_owner` for packs 5-7 has gating `{M1.R4}`; after step 2 applies M1.R4, packs 5-7 transition to `owner=2`. Last-step snapshot then matches `final_state`. Car 2 alloc = 125 kW. BD1 used = 10/10.

3. **Likely additional test to add** (when writing the fix step, not now): assert that for every relay flip in `_relay_diff`, the attributed port has a non-empty `port_flips` entry in `_resolve_pack_owner`, AND that the last-step stitched snapshot equals `final_state` packs/cars exactly. The current test suite covers neither.

### Bug B fix direction

Same change as fix #1 above — Bug A and Bug B share the same fix. The step description side-effect ("Port 1 expanding" on M1.R4 → should be "Port 2 expanding") is corrected automatically because the description uses `flip.port`.

### Further spike — none required

Root cause is pinpointed with code-line evidence. Recommend proceeding directly to a fix step that:
- patches `_adjacent_pack_owners` group filter (≈ 5 lines);
- adds a regression test asserting final-step stitched snapshot ≡ `final_state` for a multi-port-per-BD scenario (the existing test suite skipped this case);
- re-runs all three baselines to confirm no regression.

### Out-of-scope observation (not part of this bug)

`WebSessionEngine._build_simulation_config` does not sort placements by `priority` despite the CLAUDE.md/SPEC-WEB-API.md claim that "Priority (FR-16) is fed into `WebSessionEngine`'s placement order". For this scenario it doesn't matter (3 cars anchor at disjoint groups), but a scenario where two cars compete for the same anchor would expose this. Worth its own ticket; not entangled with Bug A/B.

---

## §8 Workspace cleanliness

- Temporary `/tmp/repro*.py` scripts removed.
- No production code modified.
- No test files modified.
- `git status` clean on `main`.
