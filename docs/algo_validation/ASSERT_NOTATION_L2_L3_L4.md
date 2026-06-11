# L2 / L3 / L4 Assert — MCUx/Ox/Rx/ORx 記法展開

> Read-only spike. No code modified, no tests run. Per-assert expansion + notation
> translation + worked examples for every L2/L3/L4 `assert` in the two-track invariant
> harness. Tag→layer mapping was established in
> `docs/algo_validation/TRAJECTORY_AND_LOG_CONCEPT.md`; this spike only expands each one.
> Source of truth: `tests/algo_validation/helpers/{tick_checks,steady_checks,relay_invariants}.py`.

## Notation binding

| Symbol | Code construct | Verbatim evidence |
|---|---|---|
| **Ox** | absolute output (gun) index = `mcu_idx * OUTPUTS_PER_MCU + local` | `tick_checks.py:86` `gidx = mcu_idx * OUTPUTS_PER_MCU + local`; fail message `output={gidx}` (`:78`). `OUTPUTS_PER_MCU = 2` (`mcu_control.py:45`, prod read-only) ⇒ **Ox's MCU = x // 2** (steady side `home_mcu = abs_o // OUTPUTS_PER_MCU`, `steady_checks.py:119`). `gidx` is **always an output index, never a group** — no ambiguity. |
| **Rx** | inter-group SMR relay = `board.inter_group_relays[ridx]` | `tick_checks.py:183`, `relay_invariants.py:83`. `GROUPS_PER_MCU = 4` (`mcu_control.py:44`) ⇒ 3 inter-group relays per MCU, local idx 0,1,2 (R0=g0-g1, R1=g1-g2, R2=g2-g3 within a board). |
| **ORx** | output/gun relay = `board.output_relays[local]` — **distinct from Rx** | `tick_checks.py:88` `out_relay = board.output_relays[local]`. Built R_O0 (O0↔G0), R_O1 (O1↔G3) `rectifier_board.py:93-105` (prod read-only). |
| **groups g0..g15 ↔ Ox/MCUx** | abs group = `mcu_idx*GROUPS_PER_MCU + local_pos`; anchor abs = `mcu_idx*GROUPS_PER_MCU + (0 if local==0 else 3)` | `tick_checks.py:130`; `phys_mcu = abs_g // GROUPS_PER_MCU` (`steady_checks.py:120`); `base = mcu_idx*GROUPS_PER_MCU` (`relay_invariants.py:75`). |

**Confirmed layout** (prod `rectifier_board.py:38,93-105,133-148`, `mcu_control.py:44-46`, read-only):

| MCU | groups | outputs (anchor, owned-at-min) | Ox anchor abs-group = (x//2)*4 + (0 if x even else 3) |
|---|---|---|---|
| MCU0 | g0–g3 | O0 (anchor g0, {g0,g1}), O1 (anchor g3, {g2,g3}) | O0→g0, O1→g3 |
| MCU1 | g4–g7 | O2 (anchor g4, {g4,g5}), O3 (anchor g7, {g6,g7}) | O2→g4, O3→g7 |
| MCU2 | g8–g11 | O4, O5 | O4→g8, O5→g11 |
| MCU3 | g12–g15 | O6, O7 | O6→g12, O7→g15 |

All symbols map to concrete constructs — no STOP condition. **Rx (inter-group) vs ORx
(gun) is kept strictly separate below.**

---

## L2 層

### L2 station (per-tick — `tick_checks.py:210-214`)
- **概念**: Re-run `ChargingStation.validate` each tick to reject non-contiguous group intervals and multi-owner groups.
- **判斷(記法)**: For every Ox, the abs-groups owned by Ox form a gap-free `[MIN,MAX]` interval; and no group g is simultaneously owned by two outputs Oa ≠ Ob.
- **Code (verbatim)**:
```python
210	        # Residual station validation (reuse — L2 contiguity / single owner).
211	        violations = run_station_validate(eng.station)
212	        assert not violations, (
213	            f"[L2 station] step={step_index} layer=tick seed={self.seed} "
214	            f":: {violations}")
```
(`run_station_validate` → `ChargingStation.validate` `charging_station.py:87-103`: emits `f"Output {abs_o}: non-contiguous groups {groups}"` when not contiguous.)
- **例子**:
  - 場景: MCU1's O2 (anchor g4), borrowing right.
  - 正常: O2 owns {g4,g5,g6} — contiguous, each single-owned → `violations == []`, no fire.
  - 違反: O2 owns {g4, g6} (gap at g5) → `[L2 station] step=… :: ['Output 2: non-contiguous groups [4, 6]']`. (Multi-owner variant: MCU0's O0 and O1 both claim g2 → a violation string for group 2.)

### L2 (steady — present ≤ available — `steady_checks.py:75-78`)
- **概念**: No output delivers more than its allocated capacity (no over-delivery).
- **判斷(記法)**: For each charging Ox, `present_power(Ox) ≤ available_power(Ox)`.
- **Code (verbatim)**:
```python
75	            if v is not None and v.state != VehicleState.COMPLETE:
76	                assert output.present_power_kw <= output.available_power_kw + _EPS, fail(
77	                    "L2", f"output {mcu_idx*2+local} present {output.present_power_kw} "
78	                          f"> available {output.available_power_kw}")
```
- **例子**:
  - 場景: MCU0's O0 (`mcu_idx*2+local = 0`), EV charging.
  - 正常: present 125, available 125 → `125 ≤ 125+ε`, no fire.
  - 違反: present 200, available 125 → `[L2] … :: output 0 present 200 > available 125`.

### L2 (steady — single global owner — `steady_checks.py:82-89`)
- **概念**: Across the whole station every group has at most one owning output.
- **判斷(記法)**: For each abs-group g owned by Ox, no previously-seen output Oy ≠ Ox already owns g.
- **Code (verbatim)**:
```python
83	        for local in range(OUTPUTS_PER_MCU):
84	            abs_o = mcu_idx * OUTPUTS_PER_MCU + local
85	            for abs_g in board.module_assignment.get_groups_for_output(abs_o):
86	                prev = global_owner.get(abs_g)
87	                assert prev is None or prev == abs_o, fail(
88	                    "L2", f"group {abs_g} claimed by outputs {prev} and {abs_o}")
89	                global_owner[abs_g] = abs_o
```
- **例子**:
  - 場景: MCU0, groups g0–g3.
  - 正常: O0 owns {g0,g1}, O1 owns {g2,g3} — disjoint → no fire.
  - 違反: MCU0's O0 and O1 both claim g2 → on O1, `prev=0`, `abs_o=1`; `[L2] … :: group 2 claimed by outputs 0 and 1`.

### L2 (steady — Σowned ≤ rated — `steady_checks.py:92-98`)
- **概念**: Total power of all owned groups cannot exceed the station's total rated capacity (conservation backstop; safe to sum because single-ownership prevents double counting).
- **判斷(記法)**: `Σ over all owned g of power(g) ≤ Σ over all boards of Σ module_powers`.
- **Code (verbatim)**:
```python
92	    owned_power = 0.0
93	    for abs_g in global_owner:
94	        phys_mcu = abs_g // GROUPS_PER_MCU
95	        local_g = abs_g % GROUPS_PER_MCU
96	        owned_power += engine.station.boards[phys_mcu].groups[local_g].total_power_kw
97	    assert owned_power <= total_rated + _EPS, fail(
98	        "L2", f"Σ owned-group power {owned_power} > Σ rated {total_rated}")
```
(`total_rated = sum(sum(b.module_powers) for b in engine.station.boards)`, `:62`.)
- **例子**:
  - 場景: 4-MCU `[50,75,75,50]` station, total_rated = 1000 kW.
  - 正常: all 16 groups owned once → owned_power 1000 ≤ 1000+ε, no fire.
  - 違反: corruption surfacing g4 under both O2 and O3 past the single-owner guard pushes owned_power to 1075 → `[L2] … :: Σ owned-group power 1075 > Σ rated 1000`.

### L2 (steady — station.validate reuse — `steady_checks.py:100-102`)
- **概念**: Same contiguity + single-owner reuse as the per-tick L2 station check, re-run at quiescence.
- **判斷(記法)**: Each Ox's owned abs-groups form a gap-free `[MIN,MAX]`; no group multi-owned.
- **Code (verbatim)**:
```python
100	    # ── L2 contiguity / single owner (reuse) ─────────────────────────────
101	    violations = run_station_validate(engine.station)
102	    assert not violations, fail("L2", f"station.validate: {violations}")
```
- **例子**:
  - 場景: MCU3's O7 (anchor g15) at steady state.
  - 正常: O7 owns {g14,g15} contiguous, single-owned → no fire.
  - 違反: O7 owns {g13,g15} (gap at g14) → `[L2] … :: station.validate: ['Output 7: non-contiguous groups [13, 15]']`.

---

## L3 層

### L3 I1
- **概念**: An output's available power must lie within physical bounds — never negative, never above total station rated capacity.
- **判斷(記法)**: For every Ox: `0 ≤ available_power(Ox) ≤ Σ(all boards' module_powers)`. (Output power scalar — neither Rx nor ORx.)
- **Code (verbatim)**:
```python
100	                # I1 — available power within physical bounds.
101	                assert output.available_power_kw >= -_EPS, fail(
102	                    "L3 I1", gidx, f"negative available {output.available_power_kw}", vid)
103	                assert output.available_power_kw <= total_rated + _EPS, fail(
104	                    "L3 I1", gidx,
105	                    f"available {output.available_power_kw} > rated {total_rated}", vid)
```
- **例子**:
  - 場景: 4-MCU `[50,75,75,50]` ⇒ total_rated = 1000 kW; O0 on MCU0.
  - 正常: O0.available = 250 → within `[0,1000]`, no fire.
  - 違反: O0.available = −25 → `[L3 I1] … output=0 … :: negative available -25.0`; or 1025 → `available 1025.0 > rated 1000`.

### L3 I2
- **概念**: An engaged (gun-CLOSED, not tearing-down) output must always retain at least its anchor group's power.
- **判斷(記法)**: If **ORx = CLOSED** and not teardown: `available_power(Ox) ≥ anchor_group(Ox).total_power`. (Gate reads ORx; assertion is on Output power.)
- **Code (verbatim)**:
```python
112	                if closed and not teardown:
113	                    anchor_local = 0 if local == 0 else GROUPS_PER_MCU - 1
114	                    anchor_power = board.groups[anchor_local].total_power_kw
115	                    assert output.available_power_kw + _EPS >= anchor_power, fail(
116	                        "L3 I2", gidx,
117	                        f"available {output.available_power_kw} < anchor {anchor_power}", vid)
```
- **例子**:
  - 場景: O0 anchor = g0 (50 kW); ORx CLOSED, EV charging.
  - 正常: O0.available = 125 ≥ 50 → no fire (interval may legitimately shrink to the single anchor).
  - 違反: O0.available = 25 < 50 → `[L3 I2] … output=0 … :: available 25.0 < anchor 50.0`.

### L3 I2-close
- **概念**: SPEC §11 min-guarantee gate **at the close moment** — the gun relay may close only once available power meets its dynamic per-Output min-guarantee. Checked on the OPEN→CLOSED transition only.
- **判斷(記法)**: On **ORx** transition to CLOSED: `available_power(Ox) ≥ output_min_guarantee_kw(board.module_powers, local)`. (Gate is an ORx transition; assertion on Output power.)
- **Code (verbatim)**:
```python
169	                if out_relay.state != prev:
170	                    if out_relay.state == RelayState.CLOSED:
171	                        # §11 min-guarantee gate — asserted at the close moment
172	                        # (not continuously; see I2 above).
173	                        min_g = output_min_guarantee_kw(board.module_powers, local)
174	                        assert output.available_power_kw + _EPS >= min_g, fail(
175	                            "L3 I2-close", gidx,
176	                            f"Output closed with available {output.available_power_kw} "
177	                            f"< min_guarantee {min_g}", vid)
```
- **例子**:
  - 場景: O0 on `[50,75,75,50]` board → min_g = 50+75 = 125; ORx flips OPEN→CLOSED this tick.
  - 正常: O0.available = 125 ≥ 125 → no fire.
  - 違反: ORx closes with O0.available = 100 → `[L3 I2-close] … :: Output closed with available 100.0 < min_guarantee 125.0`.

### L3 I3
- **概念**: The four pending-relay-action indicators on the output's MCU state are structurally valid — each ∈ {0,1,2}.
- **判斷(記法)**: For Ox's MCU state, each of `pending_intergroup_close/open`, `pending_output_relay_close/open` ∈ {0,1,2}. (State counters — neither Rx nor ORx hardware.)
- **Code (verbatim)**:
```python
119	                # I3 — pending indicators are structurally valid (∈ {0,1,2}).
120	                for pname in (
121	                    "pending_intergroup_close", "pending_output_relay_close",
122	                    "pending_intergroup_open", "pending_output_relay_open",
123	                ):
124	                    pv = getattr(state, pname)
125	                    assert pv in (0, 1, 2), fail(
126	                        "L3 I3", gidx, f"{pname}={pv} out of range", vid)
```
- **例子**:
  - 場景: O0's `state.pending_intergroup_close`.
  - 正常: value 1 → no fire.
  - 違反: value 3 → `[L3 I3] … output=0 … :: pending_intergroup_close=3 out of range`.

### L3 I4
- **概念**: A closed gun relay implies that output genuinely owns its anchor group in the board's ModuleAssignment.
- **判斷(記法)**: If **ORx = CLOSED** and not teardown: `module_assignment.get_owner(anchor_abs) == Ox`. **Gate reads ORx (gun relay), not Rx**; ownership is a ModuleAssignment fact.
- **Code (verbatim)**:
```python
128	                # I4 — closed output relay ⇒ anchor group owned by it (skip teardown).
129	                if closed and not teardown:
130	                    anchor_abs = mcu_idx * GROUPS_PER_MCU + (0 if local == 0 else 3)
131	                    owner = board.module_assignment.get_owner(anchor_abs)
132	                    assert owner == gidx, fail(
133	                        "L3 I4", gidx,
134	                        f"anchor g{anchor_abs} owner={owner} != output {gidx}", vid)
```
- **例子**:
  - 場景: O1 on MCU0 → anchor_abs = 0*4+3 = g3; ORx (output_relays[1]) CLOSED, charging.
  - 正常: `get_owner(3) == 1` → no fire.
  - 違反: `get_owner(3) == 0` → `[L3 I4] … output=1 … :: anchor g3 owner=0 != output 1`.

### L3 I5
- **概念**: A fully departed output (no vehicle, not teardown) is dead — gun relay OPEN and zero present power.
- **判斷(記法)**: If `connected_vehicle is None` and not teardown: **ORx = OPEN** AND `present_power(Ox) == 0`. (Two asserts: first on ORx, second on Output power.)
- **Code (verbatim)**:
```python
136	                # I5 — fully departed output carries no power, relay open.
137	                if v is None and not teardown:
138	                    assert not closed, fail(
139	                        "L3 I5", gidx, "no vehicle but relay CLOSED", vid)
140	                    assert abs(output.present_power_kw) <= _EPS, fail(
141	                        "L3 I5", gidx,
142	                        f"no vehicle but present={output.present_power_kw}", vid)
```
- **例子**:
  - 場景: O5 idle, no vehicle, teardown False.
  - 正常: ORx OPEN, present 0 → no fire.
  - 違反: ORx still CLOSED → `[L3 I5] … output=5 … :: no vehicle but relay CLOSED`; or present 50 → `no vehicle but present=50.0`.

### L3 I6
- **概念**: SPEC §11 latch — once a gun relay is observed CLOSED for a charging EV, it must stay CLOSED until the EV is COMPLETE; no mid-charge re-open. **About ORx (gun relay) only.**
- **判斷(記法)**: Stateful latch `_engaged[Ox]`: set True when ORx CLOSED while EV charging; cleared when not charging. While latched: assert **ORx = CLOSED**. Proposition: `Ox charging (latched) ⟹ ORx = CLOSED`.
- **Code (verbatim)**:
```python
144	                # I6 — §11 latch: no mid-charge re-open (see module docstring).
145	                charging = v is not None and v.state != VehicleState.COMPLETE
146	                if not charging:
147	                    self._engaged[gidx] = False
148	                elif closed:
149	                    self._engaged[gidx] = True
150	                if self._engaged[gidx]:
151	                    assert closed, fail(
152	                        "L3 I6", gidx,
153	                        "Output relay OPEN while EV still charging (mid-charge open)", vid)
```
- **例子**:
  - 場景: O0 latched engaged, next tick EV still not COMPLETE.
  - 正常: ORx still CLOSED → no fire.
  - 違反: ORx flips OPEN while EV charging → `[L3 I6] … output=0 … :: Output relay OPEN while EV still charging (mid-charge open)`.

### L2 order B1
- **code tag = L2 order, concept = L3 (no gate deadlock)**
- **概念**: Arrival ordering — every inter-group relay required by the output's current interval must already be CLOSED **before** the gun relay closes (inter-group-before-Output). Involves **BOTH Rx and ORx**.
- **判斷(記法)**: On **ORx** OPEN→CLOSED transition, for every required local idx `ridx`: **Rridx = CLOSED**. I.e. `ORx closes ⟹ ∀ required Rridx, Rridx = CLOSED`.
- **Code (verbatim)**:
```python
178	                        if state.interval_min is not None:
179	                            req = required_local_intergroup_indices(
180	                                state.interval_min, state.interval_max,
181	                                mcu_idx, eng.mcu_controls[mcu_idx]._wrap)
182	                            for ridx in sorted(req):
183	                                assert board.inter_group_relays[ridx].state == RelayState.CLOSED, fail(
184	                                    "L2 order B1", gidx,
185	                                    f"Output closed but required inter-group R{ridx} not CLOSED", vid)
```
(`req` from `relay_invariants.py:117-134` — consecutive virtual pairs whose physical groups are consecutive and inside this MCU's territory.)
- **例子**:
  - 場景: O0 interval [g0,g1] at close → required local R0 (g0-g1). ORx flips to CLOSED this tick.
  - 正常: R0 already CLOSED → no fire.
  - 違反: ORx closed while R0 still OPEN → `[L2 order B1] … output=0 … :: Output closed but required inter-group R0 not CLOSED`.

### L2 order B2
- **code tag = L2 order, concept = L3 (no gate deadlock)**
- **概念**: Departure ordering — the gun relay may open only once the EV is COMPLETE or gone; never mid-charge. **About ORx (gun relay)**; departing Rx already opened in an earlier phase, so they are not asserted here.
- **判斷(記法)**: On **ORx** CLOSED→OPEN transition: `connected_vehicle is None` OR `vehicle.state == COMPLETE`.
- **Code (verbatim)**:
```python
186	                    else:
187	                        assert v is None or v.state == VehicleState.COMPLETE, fail(
188	                            "L2 order B2", gidx,
189	                            "Output opened while EV not COMPLETE (premature gun open)", vid)
```
- **例子**:
  - 場景: O0 ORx transitions CLOSED→OPEN this tick.
  - 正常: EV.state == COMPLETE (or v is None) → no fire.
  - 違反: ORx opens while EV.state == CHARGING → `[L2 order B2] … output=0 … :: Output opened while EV not COMPLETE (premature gun open)`.

> **Rx vs ORx summary (L3):** I1/I3 = neither relay (Output power / counters); I2 & I2-close = **gated by ORx**, assert on Output power; I4 = **gated by ORx**, asserts ownership; I5 = **ORx** (relay-open) + Output power; I6 = **ORx** only; B1 = **ORx** transition + **Rx** assertion; B2 = **ORx** only.

---

## L4 層

### L4a boundary (per-tick §9 — `tick_checks.py:216-221`)
- **概念**: Per-tick SPEC §9 boundary-consistency — the engine's validator already cross-checked adjacent MCUs' `allocated_power`/`relay_state` this step; flag any inconsistency it logged.
- **判斷(記法)**: For every adjacent MCUx/MCU(x+1) pair, the engine's `validator.boundary_log` entry for this `time_step` must have `result != "inconsistent"`.
- **Code (verbatim)**:
```python
216	        # Boundary consistency (SPEC §9): the engine's own _collect_snapshot
217	        # already ran validator.check this step; flag any inconsistency it found.
218	        bad = [e for e in eng.validator.boundary_log
219	               if e.get("time_step") == step_index and e.get("result") == "inconsistent"]
220	        assert not bad, (
221	            f"[L4a boundary] step={step_index} layer=tick seed={self.seed} :: {bad}")
```
- **例子**:
  - 場景: MCU pair (0,1), boundary groups g3/g4.
  - 正常: both MCUs report the bridge `relay_state=OPEN` and matching `allocated_power` → no `inconsistent` entry → no fire.
  - 違反: MCU0 reports boundary relay CLOSED but MCU1 reports OPEN → validator logs `result:"inconsistent"` → `[L4a boundary] … :: [{…conflicts…}]`.

### L4a (steady ownership mirror — `steady_checks.py:111-115`)
- **概念**: At quiescence, adjacent MCUs' ModuleAssignment views of the shared boundary must be symmetric (reuses production `Validator._diff_pair`).
- **判斷(記法)**: For each adjacent MCUx/MCU(x+1) pair, `validator._diff_pair(x, x+1)` returns `[]`.
- **Code (verbatim)**:
```python
111	    # ── L4a ownership mirror (reuse Validator._diff_pair) ────────────────
112	    N = engine.station.num_mcus
113	    for left, right in adjacent_pairs(N):
114	        conflicts = engine.validator._diff_pair(left, right)
115	        assert not conflicts, fail("L4a", f"MCU pair ({left},{right}) ownership: {conflicts}")
```
- **例子**:
  - 場景: MCU pair (0,1).
  - 正常: O0 borrowed g4 from MCU1; both boards record g4→O0 → `_diff_pair(0,1)==[]` → no fire.
  - 違反: MCU0 records g4→O0 but MCU1 shows g4 idle → `[L4a] … MCU pair (0,1) ownership: [...]`.

### L4b (steady borrow reconciliation — `steady_checks.py:117-126`)
- **概念**: Closed-loop check for cross-MCU borrows — every group whose owner lives in a different MCU than where the group physically sits must be mirrored by the lender's own MA.
- **判斷(記法)**: For each owned group `abs_g` with owner Ox where `home_mcu = x//2 ≠ phys_mcu = abs_g//4`, the lender board must satisfy `get_owner(abs_g) == Ox`.
- **Code (verbatim)**:
```python
117	    # ── L4b borrow closed-loop (lender mirrors borrower) ─────────────────
118	    for abs_g, abs_o in global_owner.items():
119	        home_mcu = abs_o // OUTPUTS_PER_MCU
120	        phys_mcu = abs_g // GROUPS_PER_MCU
121	        if home_mcu == phys_mcu:
122	            continue  # local, not a cross-MCU borrow
123	        lender_owner = engine.station.boards[phys_mcu].module_assignment.get_owner(abs_g)
124	        assert lender_owner == abs_o, fail(
125	            "L4b", f"borrowed group {abs_g} owned by {abs_o} but lender MCU "
126	                   f"{phys_mcu} sees {lender_owner}")
```
- **例子**:
  - 場景: MCU1 (O2, home_mcu=1) borrows MCU2's g8 (phys_mcu=2).
  - 正常: MCU2's MA records g8 lent to O2 → `lender_owner == 2` → no fire.
  - 違反: MCU2 does not record it → `[L4b] borrowed group 8 owned by 2 but lender MCU 2 sees None`.

### A1 (steady relay↔ownership co-ownership — `steady_checks.py:108-109`, `relay_invariants.py:80-92`)
- **概念**: At quiescence, an inter-group (or bridge) relay's CLOSED/OPEN state must be the exact iff-mirror of whether the two groups at its ends are co-owned by a single output.
- **判斷(記法)**: For inter-group relay MCUx.Ri spanning groups g,g+1: **Ri CLOSED ⟺ g and g+1 co-owned by the same single Ox**. (Subject is **Rx**, the inter-group relay — *not* ORx.) Same iff for a bridge spanning `left.g3 / right.g0`.
- **Code (verbatim — inter-group branch; bridge branch `:94-112` is the structurally identical iff, elided)**:
```python
80	        for i in range(GROUPS_PER_MCU - 1):
81	            g, g1 = base + i, base + i + 1
82	            co_owned = owners[g] is not None and owners[g] == owners[g1]
83	            closed = board.inter_group_relays[i].state == RelayState.CLOSED
84	            if co_owned and not closed:
85	                out.append(
86	                    f"M{mcu_idx}.R{i} OPEN but g{g},g{g1} co-owned by O{owners[g]}")
87	            elif closed and not co_owned:
88	                if i in _ANCHOR_INTERGROUP_IDX and pristine:
89	                    continue  # A3: untouched board's standing anchor path
90	                out.append(
91	                    f"M{mcu_idx}.R{i} CLOSED but g{g},g{g1} not co-owned "
92	                    f"(owners O{owners[g]}, O{owners[g1]})")
```
```python
108	    relay_viol = relay_ownership_violations(engine)
109	    assert not relay_viol, fail("A1", "; ".join(relay_viol))
```
- **例子**:
  - 場景: MCU0, R1 (`inter_group_relays[1]`, spans g1-g2).
  - 正常: O0 owns both g1,g2 and R1 CLOSED → no append.
  - 違反: O0 owns g1,g2 but R1 OPEN → `[A1] … M0.R1 OPEN but g1,g2 co-owned by O0`; or R1 CLOSED with g1,g2 unowned (non-pristine) → `M0.R1 CLOSED but g1,g2 not co-owned (owners ONone, ONone)`.
- **Bug link**: A1 is the check that caught the cross-MCU **orphan-relay** regression — a cross-MCU borrower (O0) departs but lender MCU1's inter-group Rx is left stuck CLOSED while its groups are no longer co-owned, so the "CLOSED but not co-owned" branch fires (`test_cross_mcu_orphan_relay.py` docstring, ~step 847, seed 12345).

### A3 (pristine-init skip — A1's EXCEPTION, not an independent check — `relay_invariants.py:88-89`)
- **概念**: A3 is **not** a standalone assert. It is the single skip condition inside A1's "CLOSED but not co-owned" branch that suppresses a would-be A1 false-fire on a never-touched board.
- **判斷(記法)**: A1's `closed and not co_owned` violation is **suppressed** iff relay idx `i ∈ {0,2}` (the R0/R2 anchor-path relays = `_ANCHOR_INTERGROUP_IDX`) AND the whole board is still pristine (no group owned anywhere in its territory + relay vector still matches `initialize_relays`: R0/R2 CLOSED, R1 OPEN, all ORx OPEN, left bridge OPEN).
- **Code (verbatim)**:
```python
87	            elif closed and not co_owned:
88	                if i in _ANCHOR_INTERGROUP_IDX and pristine:
89	                    continue  # A3: untouched board's standing anchor path
```
- **When it makes A1 not fire / what would false-fail without it**: At construction, `initialize_relays` pre-closes R0 and R2 on every board with no interval/owner behind them (`relay_invariants.py:24,42-46`). On an untouched MCU, R0/R2 are therefore legitimately `CLOSED but not co-owned`; without the A3 skip, A1's second branch would fire on every idle board at settle — a pure false positive. The skip is narrowly gated (only idx 0 and 2, never R1; only while `pristine`), so a genuinely orphaned CLOSED relay on a *touched* board still fires. No independent example, per its role as an exception condition.

> **Rx vs ORx (L4):** A1/A3 operate exclusively on `board.inter_group_relays` (**Rx**) and bridge relays; **ORx** (`board.output_relays`) is never the subject of A1/A3 — it appears only in the pristine predicate as an all-OPEN precondition (`relay_invariants.py:59`).

---

## 一頁速查表

| 概念層 | code tag | track | Rx/ORx | 記法命題(精簡) |
|---|---|---|---|---|
| L2 | L2 station | tick | — | ∀ Ox: owned groups contiguous `[MIN,MAX]` ∧ 每 group 單一 owner |
| L2 | L2 present≤available | steady | — | ∀ charging Ox: `present(Ox) ≤ available(Ox)` |
| L2 | L2 single owner | steady | — | ∀ g: 至多一個 Ox 擁有 g |
| L2 | L2 Σowned≤rated | steady | — | `Σ power(owned g) ≤ Σ rated` |
| L2 | L2 station.validate | steady | — | 同 L2 station(穩態重跑) |
| L3 | L3 I1 | tick | — | `0 ≤ available(Ox) ≤ Σ rated` |
| L3 | L3 I2 | tick | gate ORx | ORx=CLOSED ⟹ `available(Ox) ≥ anchor(Ox)` |
| L3 | L3 I2-close | tick | gate ORx | ORx 轉 CLOSED ⟹ `available(Ox) ≥ min_guarantee(Ox)` |
| L3 | L3 I3 | tick | — | pending 指標 ∈ {0,1,2} |
| L3 | L3 I4 | tick | gate ORx | ORx=CLOSED ⟹ `owner(anchor(Ox)) = Ox` |
| L3 | L3 I5 | tick | ORx | v=None ⟹ ORx=OPEN ∧ `present(Ox)=0` |
| L3 | L3 I6 | tick | ORx | Ox charging(latched) ⟹ ORx=CLOSED |
| L3 | L2 order B1 *(tag=L2)* | tick | ORx+Rx | ORx 轉 CLOSED ⟹ ∀ required Rridx = CLOSED |
| L3 | L2 order B2 *(tag=L2)* | tick | ORx | ORx 轉 OPEN ⟹ v=None ∨ v=COMPLETE |
| L4 | L4a boundary | tick | — | ∀ adj pair: 本 step 無 `inconsistent` boundary log |
| L4 | L4a ownership | steady | — | ∀ adj pair: `_diff_pair = []`(ownership 對稱) |
| L4 | L4b | steady | — | cross-MCU 借入 g ⟹ lender MA `get_owner(g)=Ox` |
| L4 | A1 | steady | Rx | Ri=CLOSED ⟺ 兩端 group 由同一 Ox 共有 |
| L4 | A3 *(A1 例外)* | steady | Rx | pristine 板 R0/R2 CLOSED-but-unowned → skip A1 |

---

## Files read (audit trail)

| Path | Lines read | Notes |
|------|-----------|-------|
| `tests/algo_validation/helpers/tick_checks.py` | ~75-221 | L2 station, all L3, B1/B2, L4a boundary, notation |
| `tests/algo_validation/helpers/steady_checks.py` | ~46-126 | steady L2 (×4), L4a, L4b, A1 call site |
| `tests/algo_validation/helpers/relay_invariants.py` | ~24-134 | A1/A3, pristine predicate, B1 required-index helper |
| `tests/algo_validation/helpers/coverage_tracker.py` | occupancy/owner structs | binding cross-check |
| `tests/algo_validation/test_cross_mcu_orphan_relay.py` | docstring | A1 ↔ orphan-relay bug link |
| `simulation/modules/mcu_control.py` | 28-46 | **production read-only** — `OUTPUTS_PER_MCU`/`GROUPS_PER_MCU`, `output_min_guarantee_kw` |
| `simulation/hardware/rectifier_board.py` | 38,78-105,133-149 | **production read-only** — group/output/relay layout |
| `simulation/hardware/charging_station.py` | 87-103 | **production read-only** — `validate()` |
| `simulation/data/module_assignment.py` | 146,164 | **production read-only** — `get_owner`/`get_groups_for_output` |

### Stop-and-report gates
- None tripped. Every symbol (Ox/Rx/ORx/groups) maps to a concrete code construct;
  `gidx` is used **only** as an output index (never a group); Rx (inter-group) and ORx
  (gun) are strictly distinguished throughout. No assert core exceeded 10 lines except
  A1's 13-line loop (inter-group core pasted, structurally-identical bridge branch
  `relay_invariants.py:94-112` noted as elided). No answer required executing the harness.
