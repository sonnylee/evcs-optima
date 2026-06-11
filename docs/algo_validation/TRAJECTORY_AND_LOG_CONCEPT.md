# Trajectory & Invariant-Log Concept — Read-Only Spike

> Read-only spike answering the 3 code-level parts of Psyduck's exploration questions.
> No production or test code was modified; all "proposals" are unimplemented. Source of
> truth: the `tests/algo_validation/` harness (helpers + `test_exploration.py`).
>
> **Scope note (honest disclosure):** answering Q2's *departure* sub-question required
> reading three **production** files **read-only** (`simulation/environment/simulation_engine.py`,
> `simulation/modules/vehicle.py`, `simulation/hardware/output.py`) because departure is
> system-driven in production, not in the test harness. Nothing was written. Flagged per
> the spike's "read outside allowlist → report" gate.

## TL;DR (Psyduck 的 3 個 code-level 困惑)

1. **Q1 (trajectory):** The harness records a **`set`**, not an ordered path —
   `coverage_tracker.visited_nodes` is `set[tuple[int, Optional[str]]]`, and the JSON
   dump is *sorted* (order destroyed). You can compute set-based distributions today
   (per-seed |V|, pairwise Jaccard, per-node seed-frequency histogram) but **cannot**
   reconstruct "which node at tick t" — no time series is stored.
2. **Q2 (node L semantics):** A node key is `(occupancy_bitmask:int, L:Optional[str])`.
   Under multiple cars, **L is the SOC bucket of the single most-recently-injected
   arrival** (last-write-wins, station-wide scalar) — *not* a per-car or aggregate
   value. 766 = `1 empty node (0,⊥) + 255 occupancies × 3 SOC buckets`.
3. **Q3 (invariant log):** Two tracks (per-tick `tick_checks.py`, settle-time
   `steady_checks.py`). They are **pure `assert`s** — **no success log per tick**; a
   failure surfaces as a pytest `AssertionError` carrying a structured `[tag] step= O=
   seed= layer= :: detail` string. Healthy run = silence + a final PASS report block;
   problem run = one `AssertionError` and no report. The user's "L1–L4" does **not**
   map cleanly (see table).

## Q1 — Per-seed 軌跡與分佈

### Node key 與訪問記錄(set vs ordered)

**Verdict: unordered `set`; the dump is a *sorted* set, not a trajectory.**

`coverage_tracker.py:39`:
```python
self.visited_nodes: set[tuple[int, Optional[str]]] = set()
```

Dump structure, `coverage_tracker.py:178-187`:
```python
        visited = sorted(
            [occ, (L if L is not None else "⊥")]
            for (occ, L) in self.visited_nodes
        )
        payload = {
            "schema": "evcs-visited-v1",
            "metadata": metadata,
            "universe_size": _NODE_TOTAL,
            "visited": visited,
        }
```
`visited` is sorted by `(occupancy, L_str)` for diff-friendliness — **visit order is
destroyed**, and there is no per-node tick/step field. An in-memory `edges` dict
(`:41`) counts prev→key transition multiplicities but is **unordered, untimestamped,
and not dumped**.

`EVCS_DUMP_VISITED` (`test_exploration.py:129-145`) triggers
`tracker.dump_to_json(dump_path, metadata={...})` once at end-of-test; metadata carries
`seed, epsilon, max_steps, steps_run, termination, relay_events`. `union_coverage.py:40`
reads it back as a set: `visited = {(int(o), str(L)) for o, L in data["visited"]}`;
classification is order-agnostic — `core` = freq == n_good (`:88`), `frontier` = freq ==
1 (`:89`).

### 現在能算 / 算不出的分佈量

**Computable now** (from one visited set per seed):
- per-seed `|V_s| = len(visited)`
- pairwise Jaccard / overlap between any two seeds
- per-node visit-frequency histogram across seeds (the `freq` count in
  `union_coverage.py:73-76`)
- core / frequent / frontier partitions; cumulative-union (diminishing-returns) curve
  in file order
- per-seed L-bucket / N (popcount) distribution **over the set**

**NOT computable** (ordered trajectory missing):
- the path each seed walked (node-at-tick-t time series)
- first-visit order / arrival sequence of nodes
- per-tick dwell time, revisit counts, return times
- *directed, timestamped* transition sequence (only undirected aggregated edge counts
  exist in memory, and they aren't dumped)

### [提案,未實作] 取得有序軌跡的最小改動

> **提案,未實作.** Touches only the test-helper layer — never `simulation/`.
- Touch only `tests/algo_validation/helpers/coverage_tracker.py`.
- In `record()` (`:61`) append `(step_index, occupancy, L)` to a new instance list
  (e.g. `self._trajectory`), additive to the existing set logic — no behaviour change
  to coverage/edges.
- In `dump_to_json()` (`:168`) add a sibling key `"trajectory": [[step, occ, L], ...]`
  alongside `"visited"`, leaving `visited` byte-identical so `union_coverage.py` is
  untouched.
- Bump schema to `evcs-visited-v2` (or keep v1 and have readers ignore the unknown
  key) so existing dumps still load.

## Q2 (精確)— Node 語意 + transition 條件

### Node key 定義

`coverage_tracker.py:39` (above) + built in `record` at `coverage_tracker.py:67-68`:
```python
L = self.current_L(occupancy)
key = (occupancy, L)
```
The tuple is `(occupancy: int, L: Optional[str])`. `occupancy` is an **8-bit integer
bitmask** (bit `i` = output `i` occupied; built via `occupancy |= 1 << i` in
`reuse_adapters.py:58-61`). `L` is a **single string** ∈ `("low","mid","high")` or
`None` (⊥) — not an aggregate.

### L 在多車下的語意(定論 + verbatim)

**Definitive verdict:** under multiple vehicles, `L` is **the SOC bucket of the single
most-recently-injected arrival** (last-write-wins, station-wide scalar); it is never
combined across cars.

`coverage_tracker.py:48-57`:
```python
def note_arrival(self, soc_level: str) -> None:
    """Record that an arrival with ``soc_level`` was just injected → L."""
    if soc_level not in _SOC_LEVELS:
        raise ValueError(f"soc_level must be one of {_SOC_LEVELS}, got {soc_level!r}")
    self._last_L = soc_level

def current_L(self, occupancy: int) -> Optional[str]:
    """L for the given occupancy: ⊥ (None) when empty, else the tracked
    last-arrival bucket (§2.1)."""
    return None if occupancy == 0 else self._last_L
```
`_last_L` is a single scalar overwritten on each `note_arrival` (called once per
injection at `test_exploration.py:105`).

### Arrival / Departure transition(verbatim)

**Arrival** — `arrival_scheduler.py:85`:
```python
new_occ = occupancy | (1 << i)
```
An arrival at empty output `i` sets bit `i` via bitwise-OR; `L` is then set to that
arrival's bucket. (Live occupancy uses the same OR in `reuse_adapters.py:61`.)

**Departure** — `simulation_engine.py:228-233` (production, read-only):
```python
for i, o in enumerate(self._all_outputs):
    v = o.connected_vehicle
    if v is None or v.state != VehicleState.COMPLETE:
        continue
    mcu_idx, local_idx = i // 2, i % 2
    self.mcu_controls[mcu_idx].initiate_vehicle_departure(local_idx)
```
Departure is **system-only**: the engine clears output `i` once that EV's
`state == VehicleState.COMPLETE`. The trigger is **not literally `soc >= target` in
this loop** — it is `state == COMPLETE`, which `vehicle.py:72` reaches when
`current_soc >= target_soc`. The occupancy bit clears because `read_state_from_snapshot`
re-reads live outputs (`reuse_adapters.py:60`: `if output.connected_vehicle is not
None`), so `O → O′` shrinks at the next recorded quiescent edge. A departure leaves `L`
unchanged (only reset to ⊥ when `occupancy == 0`, `coverage_tracker.py:77-78`).

### 766 推導

`coverage_tracker.py:6-7`:
```
- **Nodes / 766** (main KPI): key = ``(occupancy_byte, L_code)``.
    766 = 1 empty node ``(0, ⊥)`` + 255 occupancies × 3 SOC buckets.
```
Confirmed constructively in `_all_nodes` (`coverage_tracker.py:110-116`): one node
`(0, None)`, then `occ` from `1..255` × 3 levels. Arithmetic: `1 + 255×3 = 766`.
It is **not** `256×3 = 768`: occupancy `0` (empty station) does not get 3 SOC buckets —
it collapses to exactly **1** special ⊥ node, so `(0,"low")/(0,"mid")/(0,"high")` (3
would-be nodes) are replaced by `(0,⊥)` (1 node): `768 − 3 + 1 = 766`. The ⊥/empty
special case is enforced by `current_L` returning `None` whenever `occupancy == 0`.

## Q3 — L1–L4 invariant log

### 實際 invariant 清單 + 用戶↔code 命名對照

**Per-tick track** (`tick_checks.py`, `TickChecks.run`) — 11 tags:
`L3 I1`, `L3 I2`, `L3 I2-close`, `L3 I3`, `L3 I4`, `L3 I5`, `L3 I6`, `L2 order B1`,
`L2 order B2`, `L2 station`, `L4a boundary`.

**Steady / settle track** (`steady_checks.py::run_steady_checks` + `relay_invariants.py`):
`L1`, `L2` (conservation + single-owner + `station.validate`), `A1` (with the `A3`
pristine-init exception folded inside), `L4a`, `L4b`.

| User says | Code actual naming | Alignment |
|---|---|---|
| L1 | `L1` (steady) | **clean 1:1** — empty ⇔ L=⊥ |
| L2 | `L2` (steady: conservation/ownership/`station.validate`) **+** `L2 order B1/B2`, `L2 station` (per-tick) | **split** — "L2" is an umbrella across BOTH tracks; relay-order (B1/B2) is per-tick, conservation is steady |
| L3 | `L3 I1..I6` + `I2-close` (per-tick only) | **expands to 6–7 sub-invariants**, not one |
| L4 | `L4a boundary` (per-tick §9) **+** `L4a` ownership mirror (steady) **+** `L4b` (steady) | **split into L4a/L4b; `L4a` is reused for two different things** |
| (none) | `A1` / `A3` (steady, relay↔ownership) | **no L-number** — exist in code with no user-facing L-label |

So the user's clean 4-row "L1–L4" does **not** map cleanly: L2 and L4 each fan out
across both tracks, L3 is 6–7 sub-checks, and A1/A3 carry no L-number at all.

### 每條:檢查什麼 + verbatim assert

- **L3 I1** — available power within physical bounds. `tick_checks.py:101`
  `assert output.available_power_kw >= -_EPS, fail("L3 I1", gidx, f"negative available {output.available_power_kw}", vid)` (and `:103` `<= total_rated`).
- **L3 I2** — engaged output keeps ≥ its anchor group. `:115`
  `assert output.available_power_kw + _EPS >= anchor_power, fail("L3 I2", gidx, f"available {output.available_power_kw} < anchor {anchor_power}", vid)`.
- **L3 I2-close** — §11 min-guarantee gate at the close transition. `:174`
  `assert output.available_power_kw + _EPS >= min_g, fail("L3 I2-close", gidx, ...)`.
- **L3 I3** — pending indicators ∈ {0,1,2}. `:125`
  `assert pv in (0, 1, 2), fail("L3 I3", gidx, f"{pname}={pv} out of range", vid)`.
- **L3 I4** — closed relay ⇒ anchor owned by it. `:132`
  `assert owner == gidx, fail("L3 I4", gidx, f"anchor g{anchor_abs} owner={owner} != output {gidx}", vid)`.
- **L3 I5** — departed output is dead (relay open, no power). `:138`
  `assert not closed, fail("L3 I5", gidx, "no vehicle but relay CLOSED", vid)`.
- **L3 I6** — §11 latch, no mid-charge re-open. `:151`
  `assert closed, fail("L3 I6", gidx, "Output relay OPEN while EV still charging (mid-charge open)", vid)`.
- **L2 order B1** — every required inter-group relay CLOSED before the gun closes. `:183`
  `assert board.inter_group_relays[ridx].state == RelayState.CLOSED, fail("L2 order B1", gidx, f"Output closed but required inter-group R{ridx} not CLOSED", vid)`.
- **L2 order B2** — gun opens only when EV COMPLETE/gone. `:187`
  `assert v is None or v.state == VehicleState.COMPLETE, fail("L2 order B2", gidx, "Output opened while EV not COMPLETE (premature gun open)", vid)`.
- **L2 station** (per-tick, reused) — contiguity / single-owner via `ChargingStation.validate`. `:212`
  `assert not violations, (f"[L2 station] step={step_index} layer=tick seed={self.seed} :: {violations}")`.
- **L4a boundary** (per-tick §9) — no inconsistent boundary log entry this step. `:220`
  `assert not bad, (f"[L4a boundary] step={step_index} layer=tick seed={self.seed} :: {bad}")`.
- **L1** (steady) — `steady_checks.py:55/60`
  `assert L is None, fail("L1", f"empty station but L={L!r}")` / `assert L in ("low","mid","high"), fail("L1", f"occupied but L={L!r}")`.
- **L2 conservation** (steady) — `:76` `assert output.present_power_kw <= output.available_power_kw + _EPS, fail("L2", ...)`; `:87` single-owner; `:97` Σowned ≤ rated; `:102` `station.validate`.
- **A1/A3** (steady) — `:109` `assert not relay_viol, fail("A1", "; ".join(relay_viol))`;
  messages built in `relay_invariants.py:85/91/106/110`, e.g.
  `f"M{mcu_idx}.R{i} CLOSED but g{g},g{g1} not co-owned (owners O{owners[g]}, O{owners[g1]})"`; A3 is the pristine-init skip at `relay_invariants.py:88-89`.
- **L4a ownership** (steady) — `:115`
  `assert not conflicts, fail("L4a", f"MCU pair ({left},{right}) ownership: {conflicts}")`.
- **L4b** (steady) — `:124`
  `assert lender_owner == abs_o, fail("L4b", f"borrowed group {abs_g} owned by {abs_o} but lender MCU {phys_mcu} sees {lender_owner}")`.

### Fail log 格式(verbatim)

Both tracks use a local `fail()` helper that **returns** the assert-message string (it
does not print — it is the `AssertionError` payload).

Per-tick (`tick_checks.py:75-80`):
```python
return (
    f"[{tag}] step={step_index} sim_time={eng.time_controller.current_time:.0f}s "
    f"O={occ:0{len(eng._all_outputs)}b} output={gidx} vehicle={vid} "
    f"layer=tick seed={self.seed} :: {detail}"
)
```
Steady (`steady_checks.py:46-51`):
```python
return (
    f"[{tag}] step={step_index} sim_time={engine.time_controller.current_time:.0f}s "
    f"O={occ:0{len(engine._all_outputs)}b} L={tracker.current_L(occ)} "
    f"layer=steady seed={seed} :: {detail}"
)
```
A failure carries: invariant **tag**, **step index**, sim_time, occupancy bitmask `O`,
output index + vehicle id (tick) or `L` bucket (steady), **`layer=tick|steady`**,
**seed**, and a `:: detail`. It surfaces as a pytest `AssertionError` with this string.

### Success logging:否(per invariant)

**No invariant logs anything on success** — both tracks are pure `assert`/raise-in-place.
The only success output is the end-of-run `_print_report` (`test_exploration.py:148-214`),
printed once via `print()` (visible under `pytest -s`), with static lines
`"[Steady army]  all PASS (assert-in-place)"` / `"[Per-tick army]  all PASS
(assert-in-place)"` plus run stats and coverage. It is a summary, not a per-tick log.

### 目測指南(健康 vs 異常)

- **Healthy run:** zero per-invariant output during the loop (per-tick army silent every
  step; steady army asserts only at quiescent rising edges), ending with the single
  `=== STEP S2.X v4 EXPLORATION REPORT (F1) ===` block showing both "all PASS" lines,
  `steps=`, `relay_events=`, and the **F1-b** line "anchor inter-group relay opened
  while charging: N ticks" with **N > 0**.
- **Problem run:** terminates early with a pytest `AssertionError` whose message is
  exactly one `fail()` string — read the leading `[tag]` (e.g. `[L3 I6]`, `[A1]`,
  `[L4b]`) for which invariant, `layer=tick|steady` for which track, and
  `step=/O=/seed=/vehicle=` to localise. The report block is **not** printed.
- **Trap state:** report present but **N == 0** — the explicit guard at
  `test_exploration.py:123` fails because the inter-group / A1 checks were vacuous
  (demand too low). Green-looking but abnormal.
- Mnemonic: report present + N > 0 = green; `AssertionError [tag]…` with no report =
  red; report present but N == 0 = trap.

### [提案,未實作] 最小 additive log

> **提案,未實作.** A structured per-failure message and an end-of-run report already
> exist; what is missing is a per-tick/per-invariant **success** trace. A minimal
> additive log would live in the `on_tick` hook, gated by an env flag so default
> behaviour is byte-identical:
```python
# 提案,未實作 — emit one line per settle point, success included
if os.environ.get("EVCS_INVARIANT_LOG"):
    print(f"[OK] step={completed_step} layer={'steady' if q else 'tick'} "
          f"O={occ:0{n}b} seed={SEED} checks=L1,L2,L3,A1,L4a,L4b")
```
This reuses the existing `[tag] step= O= seed=` field grammar so success and failure
lines are grep-comparable on the same `:: ` axis.

## Files read (audit trail)

| Path | Lines read | Notes |
|------|-----------|-------|
| `tests/algo_validation/helpers/coverage_tracker.py` | full (~190) | node key, dump, 766 |
| `tests/algo_validation/helpers/arrival_scheduler.py` | node-key gen (~85) | arrival bit-op |
| `tests/algo_validation/helpers/arrive_inject.py` | arrival mechanics | in scope |
| `tests/algo_validation/test_exploration.py` | tick loop + report (~11-220) | call sites, dump trigger, report |
| `tests/algo_validation/union_coverage.py` | full (~90) | union / core / frontier |
| `tests/algo_validation/sweep_union.sh` | full | sweep wiring |
| `tests/algo_validation/helpers/tick_checks.py` | full (~220) | per-tick track |
| `tests/algo_validation/helpers/steady_checks.py` | full (~125) | steady track |
| `tests/algo_validation/helpers/relay_invariants.py` | full (~110) | A1/A3 |
| `tests/algo_validation/helpers/quiescence.py` | full | settle detection |
| `tests/algo_validation/helpers/reuse_adapters.py` | occupancy build (~58-61) | live occupancy |
| `simulation/environment/simulation_engine.py` | departure loop (~228-233) | **production, read-only** (Q2 departure) |
| `simulation/modules/vehicle.py` | COMPLETE trigger (~72) | **production, read-only** |
| `simulation/hardware/output.py` | clear-on-departure (~54) | **production, read-only** |

### Stop-and-report gates encountered
- **L-naming mismatch (anticipated gate):** the user's "L1–L4" does **not** map to
  exactly 4 code invariants — documented in the Q3 mapping table rather than forced.
- **Read outside allowlist:** Q2's departure answer required reading 3 production files
  **read-only** (no writes). Flagged in the scope note + audit trail.
- No other gates tripped; no answer required executing the harness.
