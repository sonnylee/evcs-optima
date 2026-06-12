# SPIKE: A1 bridge failure (seed 1, step 3099) — Diagnosis

> Read-only diagnostic spike. No production or test code was modified. Observation
> done via `pytest` repro + a throwaway `/tmp` script (not committed, since deleted).
> This document is the only file written by the spike.

The fire under investigation:

```
[A1] step=3099 sim_time=3100s O=01001001 L=low layer=steady seed=1 ::
bridge(0,1) CLOSED but boundary g3,g4 not co-owned (owners ONone, ONone)
```

---

## TL;DR — Verdict

- [x] **(A) 真 orphan bug** — bridge 借入後離場該開卻 CLOSED,A1 正確抓到。
- [ ] (B) A1 誤報:bridge 分支缺合法狀態豁免。
- [ ] (C) 無法判定。

**One line:** O2 (MCU1.O0, anchor g4) borrowed MCU0.g3 across the (0,1) boundary at
step 3046 (bridge legitimately CLOSED). On departure at step 3093 the bridge was
**correctly OPENed**, but in the very next tick (step 3094) a concurrent relay
reconciliation **re-CLOSED** it while g3/g4 were already released — and it was never
reopened. A1 catches the resulting closed-unowned bridge at the next steady eval
(step 3099). There is **no legal closed-unowned-bridge state**, so A1 is correct; the
failure is a genuine orphan. This is a teardown/re-close **race**, distinct from C1's
"never-opened" gap — C1 closed the queue→drain path but did not close this race.

---

## 現場 (Explorer 1)

Reproduced verbatim and deterministically:
`EVCS_SEED=1 EVCS_EPSILON=0.0 python -m pytest tests/algo_validation/test_exploration.py -x -q`
fires the `steady_checks.run_steady_checks` → `relay_ownership_violations` A1 assert at
step 3099, exactly as reported.

### Fire 點 relay + ownership 狀態 (verbatim @ step 3099)

```
MCU0 inter_group_relays: R01=OPEN  R12=OPEN  R23=OPEN
MCU0 left_bridge_relay : MCU0_BR=OPEN
MCU1 inter_group_relays: R01=OPEN  R12=OPEN  R23=OPEN
MCU1 left_bridge_relay : MCU1_BR=CLOSED      <-- bridge(0,1), the orphan
Ownership: g0=O0  g1..g6=None  g7=O3        (g3=None, g4=None confirmed)
O=01001001 -> active outputs O0, O3, O6
  O0 (MCU0.O0): groups=[0]              relay CLOSED, present 50kW (low)
  O3 (MCU1.O1): groups=[7]              relay CLOSED, present 50kW (low)
  O6 (MCU3.O0): groups=[12,13,14,15]    relay CLOSED, present 250kW
```

None of the three live outputs touches the (0,1) boundary — the closed bridge
gates nobody (g3 and g4 are both unowned). It is a true orphan.

### 成因序列 (bridge CLOSE @ / g3,g4 釋放 @)

- **Borrow-in @ step 3046:** O2 (MCU1.O0, anchor g4) borrows leftward across the
  (0,1) boundary, taking g3 from MCU0. `g3` owner → O2; `MCU1_BR OPEN→CLOSED`.
  g3=O2, g4=O2 co-owned → bridge legitimately CLOSED. **Legal at this point.**
- **Departure @ steps 3093→3094:** O2 reaches COMPLETE (SOC 90). `_finalize_departure`
  releases g3 (foreign) and g4 (local): g3=None, g4=None by step 3094. Departure
  **correctly opens** its relays at 3093 (`MCU1_BR CLOSED→OPEN`, `MCU1_R01 CLOSED→OPEN`).
- **Spurious re-CLOSE @ step 3094:** in the SAME tick the bridge is driven
  `MCU1_BR OPEN→CLOSED` again (alongside `MCU0_R01 CLOSED→OPEN`, `MCU0_R23 CLOSED→OPEN`)
  by a concurrent reconciliation while g3/g4 are already unowned. Never reopened
  thereafter → boundary stays orphaned from 3094 onward.
- **A1 fire @ step 3099:** next steady eval observes closed-unowned bridge.

Ordering: borrow-CLOSE (3046) → departure-OPEN (3093) → spurious re-CLOSE (3094, never
reopened) → A1 fire (3099).

**關鍵問題答案:** 是 **"CLOSE on borrow-in, then re-closed after a correct open,
never reopened"** —— 不是「從頭到尾沒人借卻 CLOSED」。It is a real cross-MCU borrow whose
teardown was undone by a same-tick re-close race, not a missing-open.

---

## 路徑分析 (Explorer 2)

### bridge close/open code path (verbatim, `simulation/modules/mcu_control.py`)

**CLOSE** — `_compute_required_relays` adds the right-bridge when a borrow interval
crosses the boundary (`mcu_control.py:999-1004`):

```python
if self._station is not None and p == gb + GROUPS_PER_MCU - 1:
    next_g0 = (gb + GROUPS_PER_MCU) % N if self._ring_enabled else gb + GROUPS_PER_MCU
    if pn == next_g0:
        br = self._station.bridge_relay_between(self._mcu_id)
        if br is not None:
            relays.append(br)
```
Path: `_try_borrow_async:268` → assign borrowed group `:306` → `_apply_global_relay_state:307`
→ relay flipped CLOSED `:959`.

**OPEN (intended)** — borrower departure routes foreign groups through the C1 queue:
`initiate_vehicle_departure` → `_advance_relay_phases:451-505` →
`_open_departure_intergroup_relays:610` → `_finalize_departure:656` (queues foreign
releases) → `_drain_pending_foreign_release_notifies:705` → lender `_handle_return_notify:410`
→ `_sync_foreign_relays:420` → lender `_apply_global_relay_state` re-derives, bridge no
longer needed → OPEN `:946`.

### C1 (7ac4599) 是否涵蓋 bridge departure — **Yes (the queue path), but it is not the failing path here.**

C1 diff in `_finalize_departure` explicitly routes **all foreign (borrowed) groups** —
bridge-crossing included — through a deferred `ReturnNotify` instead of `_mirror_release`:

```python
+                else:
+                    # Foreign (borrowed) cell: `_mirror_release` only clears MA
+                    # mirrors — it leaves the LENDER's inter-group / bridge
+                    # relays stuck CLOSED (SPIKE-XMCU-REPORT Phase A, DP-1).
+                    # Defer a ReturnNotify so the owning MCU clears its own
+                    # authoritative MA AND resyncs its relays ...
+                    owner_mcu_id = g_phys // GROUPS_PER_MCU
+                    self._pending_foreign_release_notifies.append(
+                        (owner_mcu_id, g_phys)
+                    )
```

So the C1 **queue→drain→lender-resync** chain is complete for the bridge — that is the
"never-opened" gap (DP-1) and it is fixed.

### departure→bridge-open gap? — **No "never-opened" gap; instead a separate same-tick re-close race.**

The remaining defect is **not** in the queue→drain path. It is the teardown race that
`SPIKE-XMCU-REPORT` Phase B / the C1.5b addendum already flags in
`_apply_global_relay_state` (the departure-interval guard around `:892-905`): a departing
output's interval/sibling reconciliation, fired in the same tick as the release, can
**re-close** the bridge that departure just opened. This is exactly the step-3094
re-CLOSE Explorer 1 captured. C1 fixed *missing-open*; it did not fix *re-close-after-open*.

---

## A1 正確性 (Explorer 3)

### bridge 分支 iff (verbatim, `tests/algo_validation/helpers/relay_invariants.py`)

The branch asserts **`closed ⟺ co_owned`**, where
`co_owned = owner_l is not None and owner_l == owner_r` (≈`:101-103`). Violation message
(`:109-112`):

```
bridge(left,right) CLOSED but boundary g{g_left},g{g_right} not co-owned
```

A closed bridge whose two boundary groups are not co-owned by the same output is, by this
invariant, always illegal.

### Bridge init 狀態 — **OPEN** (verbatim)

`rectifier_board.py::initialize_relays` only closes `inter_group_relays[0]` and
`inter_group_relays[2]` and **never touches the bridge**; relays default OPEN, so the
bridge initializes OPEN. The pristine-init check even *requires* it
(`rectifier_board.py:61`): a board is only pristine if
`left_bridge_relay.state != RelayState.OPEN` is **false** — i.e. the bridge must be OPEN.

### 有無合法 closed-unowned-bridge + 有無 skip

- Inter-group relays R01/R23 are factory-preclosed, and the A1 inter-group branch has an
  **A3 pristine skip** (`relay_invariants.py:88-89`) for exactly that legal standing-closed
  state.
- The bridge has **no A3-equivalent skip** — but it also has **no legal standing-closed
  state to exempt**: it inits OPEN and is closed only by active borrow logic. So the
  missing skip is harmless; there is no legal `closed ∧ unowned` bridge configuration.

### 此狀態是否落在任何合法豁免內 — **No.**

Step 3099 is not init, g3/g4 are unowned, and no borrow interval spans the boundary.
There is no legal reason for the bridge to be CLOSED. The A1 bridge branch is **correct**
and does **not** false-positive here.

---

## 結論與後續 (不在本 spike 執行)

**Verdict (A): 真 orphan bug.** A1 correctly caught a genuinely illegal closed-unowned
bridge. The bridge was a real cross-MCU borrow (O2 ← MCU0.g3) that was correctly opened on
O2's departure (step 3093) but **re-closed by a same-tick reconciliation race at step
3094** and never reopened.

- **Root cause location:** the departure/teardown re-close race in
  `simulation/modules/mcu_control.py::_apply_global_relay_state` (departure-interval guard
  ≈`:892-905`) — a sibling/departure reconciliation in the same tick as the foreign-group
  release re-adds the bridge to the `needed` set after departure removed it. This is the
  Phase B / C1.5b teardown race noted in `docs/SPIKE-XMCU-REPORT.md`, not the C1 DP-1
  "never-opened" gap.
- **Difference from C1 (inter-group fix):** C1 (7ac4599) routed foreign-group releases
  through the `ReturnNotify` queue so the lender resyncs and opens — fixing *missing-open*.
  This bug is *open-then-re-close within the departure tick*, which the queue path does not
  guard against. A fix must prevent the same-tick reconciliation from re-closing a bridge
  whose boundary groups were just released (e.g. honor the departure guard before
  recomputing `needed`, or clear the departing interval before sibling resync runs).
- **Demo value:** this is a clean instance of "swap the seed, surface a second orphan" —
  seed 12345 never reaches this departure-race ordering; seed 1 does. The cross-seed
  exploration framework found a real, distinct orphan beyond the original
  `test_cross_mcu_orphan_relay` repro.
- **Cross-seed visualization impact:** this must be resolved (or the A1 assert made
  non-fatal for the dump path) before seeds 1/42/1000 can produce dumps, since the steady
  check aborts seed 1 at step 3099.

Fix is intentionally **not** attempted in this spike — open a separate fix instruction.

---

## Files read / executed (audit trail)

| Path | read/exec | production? |
|---|---|---|
| `tests/algo_validation/test_exploration.py` | read + exec (pytest repro) | no (test) |
| `tests/algo_validation/helpers/relay_invariants.py` | read | no (test) |
| `tests/algo_validation/helpers/steady_checks.py` | read | no (test) |
| `tests/algo_validation/helpers/{async_driver,arrive_inject,tick_checks}.py` | read | no (test) |
| `tests/algo_validation/test_cross_mcu_orphan_relay.py` | read | no (test) |
| `tests/algo_validation/conftest.py` | read | no (test) |
| `simulation/modules/mcu_control.py` | read only | **yes (untouched)** |
| `simulation/hardware/rectifier_board.py` | read only | **yes (untouched)** |
| `simulation/hardware/{charging_station,relay}.py` | read only | **yes (untouched)** |
| `simulation/log/relay_event_log.py` | read only | **yes (untouched)** |
| `git show 7ac4599` (C1 commit diff) | read | n/a |
| `docs/SPIKE-XMCU-REPORT.md` | read | n/a |
| `/tmp/observe_seed1.py` | exec only (throwaway, deleted, **not committed**) | no |
