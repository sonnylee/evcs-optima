# S2.4 Cluster C — Read-Only Assessment

**Date:** 2026-05-11
**Scope:** 3 remaining xfail tests in `services/evcs-api/tests/test_snapshot.py`
  marked with `_SPRINT1_REASON`.
**Mode:** Read-only probing — each test had its `xfail` decorator
temporarily stripped, run individually, then immediately restored via
`git checkout`. No production / test / SPEC changes are committed.

**Baseline (pre- and post-assessment):** `90 passed, 3 xfailed, 2 deselected`.

---

## §A — Method

For each target test:

1. Read source + decorator at `services/evcs-api/tests/test_snapshot.py`.
2. Strip the `@pytest.mark.xfail(...)` line in working copy.
3. Run `pytest <test> -v`.
4. Capture result + first-pass root cause.
5. `git checkout` the file. Verify clean.

Recorded outcome buckets per test (one of):
- **Pass after stripping** → genuine S2.5ab ripple effect (xfail can be removed as-is).
- **Fail with SPEC §11 floor mismatch** → relax assertion to honor floor (use helper).
- **Fail with reactive-engine group-granularity mismatch** → relax to invariant-style (range / ≥ N).
- **Fail with policy / warning gap** → needs dedicated spike or feature; defer.
- **Hard error / fixture broken** → delete or rewrite.

---

## §B — Test 1: `test_port_two_anchors_at_far_end`

**Location:** `services/evcs-api/tests/test_snapshot.py:91-97`
**Config:** `_cfg(1)` — 1 REC BD × `[50,75,75,50]`. Port 2 wants 75 kW.
**Assertion under test:** `sorted(p for _, p in owned) == [7, 8, 9]` (3 packs at far end).

### Result: FAILED

```
AssertionError: assert [5, 6, 7, 8, 9] == [7, 8, 9]
```

Captured stdout:
```
[SPEC §11] Engagement state (post-arrival, pre-settle):
  Port 2: user_max= 75 kW, engagement_avail=  125 kW, output_relay=CLOSED
```

### Root cause
Per SPEC §11 minimum-guarantee floor, Port 2's anchor (Group G3 = 50 kW)
plus its inner neighbour (G2 = 75 kW) = **125 kW floor**. Port 2's
declared `max_required = 75 kW` is below the floor; the engine raises it
to 125 kW (= 5 packs at indices 5–9). The test was written before the
floor was enforced and assumed the engine would ship sub-floor demand
verbatim.

### Disposition recommendation: **Relax assertion (use SPEC §11 floor helper)**

Bring assertion in line with the actual floor:
- Use `min_guarantee_for_output(...)` helper introduced in S2.5c, or
  inline-assert `len(owned) == 5` and `sorted(...) == [5,6,7,8,9]`.
- Keep the "anchor at far end" intent: assert max pack index == 9.

This is a Dim B issue (SPEC §11 floor enforcement). One-shot edit; no
production change. ~5 min.

---

## §C — Test 2: `test_priority_determines_allocation_order`

**Location:** `services/evcs-api/tests/test_snapshot.py:176-192`
**Config:** `_cfg(2)` — 2 REC BDs = 20 packs / 500 kW. Two ports each
want 300 kW (12 packs); priorities 1 vs 2.
**Assertion under test:** `len(owned_p2) == 12` (priority-1 fully
satisfied at 300 kW exact).

### Result: FAILED

```
AssertionError: expected 12 packs for priority-1 port, got 13
  +  where 13 = len([(1, 5), (1, 6), (1, 7), (1, 8), (1, 9), (2, 0), ...])
```

### Root cause
Reactive engine borrows in **group granularity**, not pack granularity.
A 300 kW request snaps to the smallest group-aligned ≥ 300 — here
50+75+75 (home) + 50+75+50 = 375 kW... actually the trace shows 13
packs = 325 kW, the smallest group-aligned ≥ 300 reachable from Port 2's
anchor side. This is the **same root cause already documented and
worked-around** in `test_overflow_borrows_from_right_neighbor`
(see lines 104-121: "Reactive engine borrows in group granularity (not
pack-by-pack), so actual allocation snaps to the smallest group-aligned
≥ 400 kW.")

The priority **direction** is correct — Port 2 (priority 1) wins more
packs than Port 1 (priority 2). Only the exact count is wrong.

### Disposition recommendation: **Relax assertion (invariant-style)**

Mirror the pattern already used in
`test_overflow_borrows_from_right_neighbor`:
- `assert len(owned_p2) >= 12, "priority-1 port should hold ≥ requested"`
- `assert len(owned_p2) > len(owned_p1), "priority-1 should outrank priority-2"`
- `assert len(owned_p1) + len(owned_p2) <= 20`
- Keep the warnings assertion (depends on §D outcome — see warning gap).

This is a Dim D issue (group-granularity). FR-16 priority logic is
working; the test's literal-count assertion is over-tight. ~5 min.

---

## §D — Test 3: `test_oversubscribed_emits_warnings`

**Location:** `services/evcs-api/tests/test_snapshot.py:225-231`
**Config:** `_cfg(1)` — 1 REC BD = 250 kW. Two ports each want 200 kW
(total 400 > 250).
**Assertions under test:**
1. `total_requested_kw == 400` ✅ (confirmed via partial trace)
2. `total_power_kw == 250` ✅ (full station delivered: 125 kW × 2)
3. `any("only" in w or "starved" in w for w in snap["warnings"])` ❌

### Result: FAILED — distinct from §B and §C

```
assert False
 +  where False = any(<generator ... in snap["warnings"]>)
```

Captured stdout:
```
Port 1: user_max=200 kW, engagement_avail=  125 kW, output_relay=CLOSED
Port 2: user_max=200 kW, engagement_avail=  125 kW, output_relay=CLOSED
```

### Root cause
Each port settles at **125 kW** (the SPEC §11 floor) instead of its
requested 200 kW. Total delivered = 250 kW = full station capacity.
The engine considers the station fully utilised, so no
"station-oversubscribed" warning fires. But each port is individually
under-served (125 kW vs 200 kW requested), and the test expected a
**per-port starvation** warning.

This is a **policy gap** rather than a bug-in-existing-logic:
- Engine emits warnings on station-level oversubscription.
- It does not emit warnings on per-port shortfall when station is at
  capacity.
- SPEC-WEB-API.md FR-08 / FR-14 talk about "warnings" abstractly but do
  not nail down per-port-shortfall semantics.

### Disposition recommendation: **Further spike required (Sprint 2 / 3)**

Two viable options, both larger than a stage-2 mechanical change:

A. **Add per-port-shortfall warning emission** in
   `state_calculation_service.py` / `WebSessionEngine`. Requires a
   small policy decision (which thresholds count as "starved"?) and
   touches production warning code — beyond stage 2's mechanical-only
   scope.

B. **Reframe the test** as an "engine gracefully clamps to station
   capacity" check (drop the warning assertion, keep the
   `total_power_kw == 250` invariant). Quicker but loses the FR-14
   warning regression coverage.

Recommend: keep `xfail` through stage 2; open a follow-up spike to
decide A vs B with product input. **Do not strip the decorator in
S2.4 stage 2.**

---

## §5.M1 — `_SPRINT1_REASON` constant

If stage 2 follows the dispositions above:

- §B fix → assertion change (no longer an "envelope" issue)
- §C fix → assertion change (no longer an "envelope" issue)
- §D stays `xfail` but with a **different reason string** (per-port
  shortfall warning policy gap, not Sprint 1 envelope).

**Verdict:** Stage 2 should **delete** the `_SPRINT1_REASON` constant
and inline a new, more precise reason on the §D decorator. The constant
dates to F09.2 envelope-locking; once §B and §C have specific
non-envelope assertions, lumping them under one xfail reason was
already misleading.

---

## §5.M2 — Predicted baseline after stage 2

| Outcome | Count |
|---|---|
| Stripped + assertion-relaxed: §B passes | +1 → 91 passed |
| Stripped + assertion-relaxed: §C passes | +1 → 92 passed |
| §D keeps `xfail` with new reason | xfailed: 1 |

**Predicted post-stage-2 baseline:** `92 passed, 1 xfailed, 2 deselected`.
(Down from 90 passed / 3 xfailed.)

If §D is also reframed as option B (drop warning assertion), then
`93 passed, 0 xfailed, 2 deselected`.

---

## §5.M3 — Stage 2 work estimate

Files expected to change in stage 2:

| File | Change | Est. |
|---|---|---|
| `services/evcs-api/tests/test_snapshot.py` | Strip 2 decorators, rewrite assertions for §B and §C, update §D reason string | 30 min |
| `services/evcs-api/tests/test_snapshot.py` (top) | Delete `_SPRINT1_REASON` constant; replace with inline reason on §D | 5 min |

**No production code changes.** No SPEC changes.

If §D is dispositioned A (add per-port-shortfall warning), add ~2 hours
on `state_calculation_service.py` + `web_session_engine.py` + new test —
but this is out of scope for stage 2 as scoped.

**Total stage 2 (test-only):** ~35 min.

---

## §6 — Stage 2 overall recommendation

1. Treat §B and §C as mechanical assertion relaxations against now-known
   engine behaviour (SPEC §11 floor + group-granularity). Both have
   prior precedent in the same file
   (`test_overflow_borrows_from_right_neighbor`,
   `test_priority_higher_number_still_gets_nonzero_when_capacity_allows`),
   so the rewrite pattern is established — no novel design.
2. Treat §D as a real policy gap. Keep it `xfail` with a distinct reason
   pointing to the spike, not to the envelope.
3. Drop `_SPRINT1_REASON` — its scope shrunk to a single test, no longer
   warranting a shared constant.

Stage 2 is purely test-and-comment work, ~35 min, no production change.

---

## §7 — Probe-session integrity

- All 3 decorators stripped one at a time and `git checkout`-restored
  before moving to next test.
- No restore was ever forgotten — `git status` returned clean after
  each restore.
- No production / SPEC file ever modified.
- Final `git status` (this report writing): only this report file as
  untracked.
- Final backend baseline (post-restore, pre-report): `90 passed, 3
  xfailed, 2 deselected` — unchanged from start.
