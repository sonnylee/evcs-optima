# S2.0 — Dynamic Groups Assessment

> Scope: read-only audit of `simulation/` and `services/evcs-api/app/`.
> Question: should Sprint 2 make **group COUNT per MCU** variable (currently locked at 4),
> or only make **group POWER** variable (each of 4 groups can be 50/75/100 kW)?
> Output: §5 recommendation A vs B for Sprint 2 design Q1.

Date: 2026-05-08 · Branch: `main` · Last commit: `7027673`

---

## §1. Background — what `GROUP_CONFIGS = [2, 3, 3, 2]` actually is

`simulation/hardware/rectifier_board.py:16`:

```python
GROUP_CONFIGS = [2, 3, 3, 2]  # num SMRs per group (×25kW each)
```

Two facts stack here:

1. **Length 4 = group count per MCU.** Hardcoded array literal; one entry per group.
2. **Each value = number of 25 kW SMRs in that group.** `[2,3,3,2]` ⇒ 50/75/75/50 kW.

So the array encodes *both* dimensions in one literal. Sprint 2 FR-11 must decide whether to
loosen one dimension or both:

- **Dim A — group count per MCU** (length of `GROUP_CONFIGS`)
- **Dim B — power per group** (each entry's value, which is `power/25`)

Sprint 1 freezes both at "4 groups, 50/75/75/50". The web layer's `RecBdConfig.module_powers`
already accepts a `List[int]` (validated as 25 kW multiples), so the API surface is
already shaped for variable-length lists; the simulation core is what's locked.

---

## §2. Hit table — all locations classified

Hits keyed by file:line. `(L)` = literal-constant site, `(I)` = index/arithmetic site,
`(A)` = array-literal site, `(D)` = derived/import-only site (cosmetic). Counts in §3.

### 2.1 simulation/

| File:line | Kind | Snippet | Assumption locked |
|---|---|---|---|
| `simulation/utils/topology.py:13` | L | `GROUPS_PER_MCU = 4` | group count per MCU |
| `simulation/utils/topology.py:14` | L | `OUTPUTS_PER_MCU = 2` | output count per MCU (depends on #ports/REC BD, not groups) |
| `simulation/utils/topology.py:50` | I | `return abs_group_idx // GROUPS_PER_MCU` | global→MCU index conversion |
| `simulation/modules/mcu_control.py:31` | L | `GROUPS_PER_MCU = 4` | duplicate of topology constant |
| `simulation/modules/mcu_control.py:33` | A | `ANCHOR_GROUP_LOCAL_IDX = (0, GROUPS_PER_MCU - 1)` | anchors are first/last group only |
| `simulation/modules/mcu_control.py:100,102` | I | `mcu_id * GROUPS_PER_MCU`; `GROUPS_PER_MCU * num_mcus` | global base + ring length |
| `simulation/modules/mcu_control.py:113` | I | `self._local_to_global(ANCHOR_GROUP_LOCAL_IDX[i])` | each output's anchor read from the (0, last) tuple |
| `simulation/modules/mcu_control.py:426` | I | `owner_mcu = rg // GROUPS_PER_MCU` | absolute group → owning MCU |
| `simulation/modules/mcu_control.py:617` | I | `range(self._group_base, self._group_base + GROUPS_PER_MCU)` | local-group iteration in return scan |
| `simulation/modules/mcu_control.py:850` | I | `range(self._group_base, self._group_base + GROUPS_PER_MCU)` | same pattern, different call site |
| `simulation/modules/mcu_control.py:921-922` | I | `if gb <= p <= gb + 2 and pn == p + 1: relays.append(self._board.inter_group_relays[p - gb])` | hardcoded `gb + 2` (= last inter-group index for 4 groups → 3 inter-group relays indexed 0..2) |
| `simulation/modules/mcu_control.py:934-935` | I | `p == gb + GROUPS_PER_MCU - 1`; `next_g0 = (gb + GROUPS_PER_MCU) % N` | bridge-edge detection |
| `simulation/modules/mcu_control.py:962-963,1070,1077,1084-1085` | I | `g_global // GROUPS_PER_MCU`; `g_global % GROUPS_PER_MCU` | absolute↔local conversion (5 sites) |
| `simulation/data/relay_matrix.py:19,28` | D/L | `from … GROUPS_PER_MCU`; `WINDOW_GROUPS_3MCU = 3 * GROUPS_PER_MCU` | 3-MCU window sizing |
| `simulation/data/relay_matrix.py:41` | I | `self.num_groups = GROUPS_PER_MCU` (single-MCU branch) | matrix dimension |
| `simulation/data/relay_matrix.py:63,82-83,107,110,121,127,147` | I | repeated `slot * GROUPS_PER_MCU + offset`; `abs_g // GROUPS_PER_MCU` | matrix slot↔abs translation (7 sites) |
| `simulation/data/relay_matrix.py:66` | I | `for i in range(3):` | inter-group relay loop — hardcoded `3` (= GROUPS_PER_MCU − 1) |
| `simulation/data/relay_matrix.py:70` | I | `self._set_pair_local(base_o + 1, base_g + 3, 0)` | output-1 anchored to group 3 (last of 4) |
| `simulation/data/module_assignment.py:20,26` | D/L | import + `WINDOW_GROUPS_3MCU = 3 * GROUPS_PER_MCU` | window sizing |
| `simulation/data/module_assignment.py:38,67,77,90,93,106,112,199` | I | repeated `* GROUPS_PER_MCU`, `// GROUPS_PER_MCU`, `% GROUPS_PER_MCU` | slot↔abs translation (8 sites) |
| `simulation/utils/validator.py:6,90,91` | D/I | `for g_off in range(GROUPS_PER_MCU); abs_g = shared_mcu * GROUPS_PER_MCU + g_off` | boundary-consistency scan |
| `simulation/hardware/rectifier_board.py:16` | A | `GROUP_CONFIGS = [2, 3, 3, 2]` | both group count *and* per-group power |
| `simulation/hardware/rectifier_board.py:38` | I | `g_base = mcu_id * 4` | literal `4` (not the constant!) |
| `simulation/hardware/rectifier_board.py:46` | I | `for i, num_smrs in enumerate(GROUP_CONFIGS):` | builds 4 groups |
| `simulation/hardware/rectifier_board.py:52` | I | `global_groups = 4 * num_mcus` | literal `4` (not the constant) |
| `simulation/hardware/rectifier_board.py:57` | I | `for i in range(3):` | inter-group relay loop — `3` = group_count − 1 |
| `simulation/hardware/rectifier_board.py:72` | A | `for i, group_idx in enumerate([0, 3]):` | output anchors hardcoded to first/last group of 4 |
| `simulation/hardware/rectifier_board.py:79,82` | I | `node_b=self.groups[group_idx].group_id`; `matrix_idx_b=g_base + group_idx` | uses the `[0, 3]` literal |
| `simulation/hardware/rectifier_board.py:97-101` | I | `node_a=f"MCU{prev_mcu}_G3"`; `matrix_idx_a=prev_mcu * 4 + 3` | bridge anchored to neighbor's "G3" — **string-encoded** group index |
| `simulation/hardware/rectifier_board.py:114-126` | A | output 0 = `[groups[0], groups[1]]` (anchor G0); output 1 = `[groups[2], groups[3]]` (anchor G3) | initial Phase 1 partition assumes 4 groups |
| `simulation/hardware/charging_station.py:99-100` | I | `g_base = board.mcu_id * 4`; `for g_off in range(4):` | validator literal `4` |
| `simulation/environment/vision_output.py:159` | I | `row += ["OFF"] * 4` | CSV column count for `R1..R4` per MCU |

### 2.2 services/evcs-api/app/

| File:line | Kind | Snippet | Assumption locked |
|---|---|---|---|
| `services/.../web_session_engine.py:9,55-61` | D/A | docstring + `_SPRINT1_REC_BD_COUNT = 4`; `_SPRINT1_MODULE_POWERS = [50, 75, 75, 50]`; `_SPRINT1_ERROR` raised by `_validate_sprint1` | hard validator gate — **only** entry point that *enforces* the lock |
| `services/.../web_session_engine.py:165` | I | `if list(bd.module_powers) != _SPRINT1_MODULE_POWERS: raise ValueError` | rejects any other config |
| `services/.../web_session_engine.py:198` | I | `num_mcus=_SPRINT1_REC_BD_COUNT` | passes 4 to SimulationEngine |
| `services/.../web_session_engine.py:285` | I | `abs_g = mcu_idx * 4 + g_local` | snapshot extraction — literal `4` |
| `services/.../config_service.py:17,26` | A | `DEFAULT_MODULE_POWERS = [50, 75, 75, 50]`; `RecBdConfig(... module_powers=list(DEFAULT_MODULE_POWERS))` | factory default only — schema *accepts* arbitrary list |
| `services/.../config_service.py:58` | D | docstring example `[50,75,75,50] → [(0,2),(2,5),(5,8),(8,10)]` | comment only, code itself iterates `module_powers` |
| `services/.../config_service.py:62-65` | I | `for p in module_powers: cnt = p // STEP_KW` | **already dim-B-flexible** — derives pack count per group from input list |
| `services/.../adapters/step_planner.py:142` | I | `last_group = len(rec_bd.module_powers) - 1` | **already dim-A-flexible** in API layer — derives last group from list length |
| `services/.../adapters/step_planner.py:140-143` | A | `is_first = (port_id - 1) % 2 == 0`; anchor at group 0 if first else last | anchor logic = first/last group, not "0/3" |
| `services/.../schemas/config.py:21` | D | `module_powers: List[int] = Field(..., min_length=1, …)` | **schema already allows any length ≥ 1** |

---

## §3. Three-category statistics

Categories defined to make the refactor scope concrete:

| # | Category | Definition | Count |
|---|---|---|---|
| **C1** | Constant + arithmetic on `GROUPS_PER_MCU = 4` | reads of the named constant + literal-`4` math | **~31 sites** (28 in simulation/, 3 in services/) |
| **C2** | Anchor / first-and-last-group hardcoding | `[0, 3]`, `gb + GROUPS_PER_MCU - 1`, `(0, GROUPS_PER_MCU - 1)`, "G3" string | **~11 sites** (all in simulation/, plus 1 already-flexible API site) |
| **C3** | `GROUP_CONFIGS = [2, 3, 3, 2]` and the implicit `[2,3,3,2]` ↔ `[50,75,75,50]` 1-to-1 map | the array literal + `_SPRINT1_MODULE_POWERS` + factory default + the `len(GROUP_CONFIGS)`-driven group construction | **~6 sites** (1 in simulation/, 5 in services/) |

Headline counts:
- **GROUPS_PER_MCU constant** named: 41 grep hits (definition + 39 references + 1 import).
- **literal `4` arithmetic** that should be `GROUPS_PER_MCU` (or worse, group-count-dependent) but isn't: 5 sites in simulation/, 2 in services/.
- **`[2,3,3,2]` / `[50,75,75,50]` array literals**: 1 in simulation/, 5 in services/.
- **anchor/home_group references**: 61 grep hits (most are correct usage of an internal `anchor_group_idx` field; the *hardcoded* anchor sites that would break with variable group count are 5: `rectifier_board.py` lines 14, 72, 97, 109-110, 121).

---

## §4. Four focus-area deep reads

### 4.1 RelayMatrix construction (`simulation/data/relay_matrix.py`)

- Single class, ~187 lines. Window size = 18 (3 MCUs × (4 groups + 2 outputs)) when `num_mcus > 1`.
- The matrix size (`self.size`) is computed from `num_groups + num_outputs`, where each is itself derived from `GROUPS_PER_MCU * 3` and `OUTPUTS_PER_MCU * 3`. **Variable group count would cleanly cascade through this constructor** — no bare literals beyond the named constant.
- One bare-literal hazard: line 66 `for i in range(3):` (inter-group relay topology — would need `range(self.num_groups_per_mcu - 1)`) and line 70 `self._set_pair_local(base_o + 1, base_g + 3, 0)` (output-1 wired to group `3` = last of 4). These two lines encode "first/last anchor only" — same C2 pattern as everywhere else.
- Verdict: **shape is structurally clean once you replace `GROUPS_PER_MCU` with a per-instance `num_groups_per_mcu`**. The `_translate_endpoint` math at line 147 (`global_groups = GROUPS_PER_MCU * self.num_mcus`) becomes `n × num_mcus` and Just Works.

### 4.2 ModuleAssignment construction (`simulation/data/module_assignment.py`)

- Mirror-shape of RelayMatrix. Same per-MCU × 3-window pattern, same constructor structure.
- All 8 `* GROUPS_PER_MCU` / `// GROUPS_PER_MCU` / `% GROUPS_PER_MCU` sites are mechanical translations — replacing the constant with a per-MCU number propagates trivially.
- `is_contiguous` (line 199) uses `N = GROUPS_PER_MCU * self.num_mcus` for ring wrap; same mechanical replacement.
- Verdict: **clean mechanical refactor**. No anchor-specific or first/last hardcodes here.

### 4.3 MCUControl borrow/return + anchor logic (`simulation/modules/mcu_control.py`)

This is the **core algorithm** and the most invasive area.

- `GROUPS_PER_MCU` appears 14 times (lines 31, 33, 100, 102, 426, 617, 850, 934, 935, 962, 963, 1070, 1077, 1085). Mechanical replacement is feasible.
- **`ANCHOR_GROUP_LOCAL_IDX = (0, GROUPS_PER_MCU - 1)`** at line 33 is the conceptual lock: it asserts "anchors are at the FIRST and LAST group, period." This is consumed at line 113 (`anchor_global = self._local_to_global(ANCHOR_GROUP_LOCAL_IDX[i])`). For variable group count, this still works (last index = `n - 1`); the design **only breaks if you also want > 2 outputs per MCU** or different anchor placement.
- **`gb + 2`** at line 921 — the `if gb <= p <= gb + 2` check identifies "is this an inter-group relay within my MCU?" The `+ 2` is `GROUPS_PER_MCU − 2` (= number of inter-group relays − 1, indexed 0..n−2). With variable group count this becomes `gb + n − 2`. Easy to fix but **easy to miss** in a search-and-replace.
- The borrow/return scan loops (`range(self._group_base, self._group_base + GROUPS_PER_MCU)` at lines 617, 850) are textbook mechanical replacements.
- The `_compute_required_relays` logic (the heart of mid-charge resource allocation) is **structurally** group-count-agnostic — it walks intervals abstractly. The brittle parts are in the relay-edge-detection branches (lines 920-940) where the `gb + 2` and `gb + GROUPS_PER_MCU - 1` arithmetic identifies edge cases.
- Verdict: **mechanical but high-risk**. Total surface area is ~14 named sites + ~3 implicit literal sites. The algorithm itself doesn't *care* about group count; the hardcodes are at the index-translation boundary.

### 4.4 Web service translation layer (`services/.../web_session_engine.py`, `step_planner.py`, `config_service.py`)

This area is **already partially flexible** for dim B (per-group power):

- `config_service.module_pack_ranges` (line 57-66) iterates `module_powers` and computes pack ranges from `p // STEP_KW`. It already handles any list length and any 25 kW multiple.
- `step_planner._anchor_group` (line 133-143) computes `last_group = len(rec_bd.module_powers) - 1`. **It does not assume group count = 4.**
- `RecBdConfig.module_powers` schema accepts `min_length=1`, no upper bound on list length.

The **only** active gate is `WebSessionEngine._validate_sprint1` (line 161-166), which rejects anything ≠ `[50,75,75,50]` × 4 MCU. Removing this gate alone would let dim-B configs propagate to the SimulationEngine — but the SimulationEngine itself would silently truncate to its hardcoded 4 groups via `GROUP_CONFIGS = [2, 3, 3, 2]` (the literal in `rectifier_board.py:16` doesn't read the API config at all — it's a module-level constant).

So `web_session_engine.py:285` (`abs_g = mcu_idx * 4 + g_local`) is one of two remaining literal-`4` sites in the API layer. The other is `_SPRINT1_REC_BD_COUNT = 4` (which is dim-A but for *MCU count*, not group count — orthogonal).

Verdict: **API layer is one parameter-passthrough away from supporting dim B** (variable per-group power within fixed 4-group layout). Dim A (variable group count) requires the simulation core changes from §4.1-4.3 above.

---

## §5. Recommendation — A or B?

**Option A — Make group COUNT (dim A) variable in Sprint 2 (full FR-11)**
- Refactor scope: ~31 named-constant sites + ~11 anchor/first-last sites + 1 array literal in core, plus removing the `_validate_sprint1` gate. ~50 sites total, spanning 6 files in simulation/ and 3 in services/.
- Adds a pluggable `num_groups_per_mcu` parameter at `RectifierBoard`, `RelayMatrix`, `ModuleAssignment`, `MCUControl`, and threads it through `SimulationConfig`.
- Major test risk: `MCUControl._compute_required_relays` (the borrow/return pathfinder) has implicit "4 groups per MCU" assumptions in its edge-detection branches (the `gb + 2` and `gb + GROUPS_PER_MCU - 1` sites in §4.3) that are mechanical to fix but easy to miss. Need to extend the regression scenarios (currently 14 in `associate/verify/`) with at least one variable-group-count case.

**Option B — Defer dim A to Sprint 3; only make group POWER (dim B) variable in Sprint 2**
- Refactor scope: ~6 sites — drop the `_validate_sprint1` per-power equality check, derive `GROUP_CONFIGS` from `RecBdConfig.module_powers` instead of using the module-level constant in `rectifier_board.py:16`, and route the per-REC-BD power list through `SimulationEngine` → `RectifierBoard` constructor.
- Group count stays at 4 across the board. All anchor/first-last/index-arithmetic hardcodes (§3 C1+C2) stay as-is — they remain correct.
- Web layer ships immediately because `module_pack_ranges` and `_anchor_group` already handle any power list.
- Existing 14 regression scenarios stay valid (same topology, just different per-group capacities).

### Final recommendation: **B**

**One-line reason:** the API and step-planner layers are already dim-B-ready, and dim B is what the FR-11 wireframe spec actually shows users typing into `module_powers` (the §4 spec's example is `"75, 100, 100, 75"` — same length, different values); dim A is not visible in any UI requirement and would force ~50 algorithm-core changes for a feature the user can't see.

If the product team later needs dim A, the §4.1 / §4.2 deep reads show the `RelayMatrix` and `ModuleAssignment` constructors are structurally clean for it — the work is mechanical replacement of `GROUPS_PER_MCU` with a per-instance value plus a careful pass through `MCUControl`'s edge-detection branches. That's a Sprint 3 item, not a Sprint 2 item.

---

## §6. Appendix — raw grep output

### A.1 `GROUPS_PER_MCU` — 41 hits

```
simulation/data/relay_matrix.py:19,28,41,63,82,83,107,110,121,127,147        (11)
simulation/data/module_assignment.py:20,26,38,67,77,90,93,106,112,199        (10)
simulation/modules/mcu_control.py:31,33,100,102,113(via tuple),426,617,850,
                                  934,935,962,963,1070,1077,1084,1085        (16 incl. tuple use)
simulation/utils/validator.py:6,90,91                                         (3)
simulation/utils/topology.py:13,50                                            (2)
```
(Note: line 113 references `ANCHOR_GROUP_LOCAL_IDX` which is itself derived from `GROUPS_PER_MCU`; counted as one indirect site.)

### A.2 Literal `* 4` / `// 4` / `% 4` / `range(4)` — 7 hits

```
simulation/hardware/charging_station.py:99    g_base = board.mcu_id * 4
simulation/hardware/charging_station.py:100   for g_off in range(4):
simulation/hardware/rectifier_board.py:38     g_base = mcu_id * 4
simulation/hardware/rectifier_board.py:52     global_groups = 4 * num_mcus
simulation/hardware/rectifier_board.py:100    matrix_idx_a=prev_mcu * 4 + 3
simulation/environment/vision_output.py:159   row += ["OFF"] * 4
services/evcs-api/app/services/web_session_engine.py:285  abs_g = mcu_idx * 4 + g_local
```

### A.3 `GROUP_CONFIGS` / `[2,3,3,2]` — 2 hits (both in same file)

```
simulation/hardware/rectifier_board.py:16   GROUP_CONFIGS = [2, 3, 3, 2]
simulation/hardware/rectifier_board.py:46   for i, num_smrs in enumerate(GROUP_CONFIGS):
```

### A.4 `[50, 75, 75, 50]` — 8 hits (all in services/)

```
services/.../web_session_engine.py:9       (docstring)
services/.../web_session_engine.py:57      _SPRINT1_MODULE_POWERS = [50, 75, 75, 50]
services/.../web_session_engine.py:59      (error message string)
services/.../web_session_engine.py:74      (docstring example)
services/.../web_session_engine.py:90      (docstring)
services/.../config_service.py:17          DEFAULT_MODULE_POWERS = [50, 75, 75, 50]
services/.../config_service.py:58          (docstring example)
services/.../schemas/config.py:21          (Field description string)
```

### A.5 `range(3)` (inter-group relay = group_count − 1) — 2 hits

```
simulation/hardware/rectifier_board.py:57   for i in range(3):
simulation/data/relay_matrix.py:66          for i in range(3):
```

### A.6 Anchor / first-last hardcodes — 5 hits

```
simulation/hardware/rectifier_board.py:14    # O0 anchored to G0, O1 anchored to G3   (comment)
simulation/hardware/rectifier_board.py:72    for i, group_idx in enumerate([0, 3]):
simulation/hardware/rectifier_board.py:97    node_a=f"MCU{prev_mcu}_G3"
simulation/hardware/rectifier_board.py:109-110  # O0: anchor=G0, groups={G0, G1} / O1: anchor=G3
simulation/modules/mcu_control.py:33         ANCHOR_GROUP_LOCAL_IDX = (0, GROUPS_PER_MCU - 1)
```

### A.7 `RelayMatrix(...)` / `ModuleAssignment(...)` constructor calls — 2 hits

```
simulation/hardware/rectifier_board.py:41    RelayMatrix(mcu_id=..., num_mcus=...)
simulation/hardware/rectifier_board.py:42    ModuleAssignment(mcu_id=..., num_mcus=...)
```
Both are constructed with **only** `mcu_id` and `num_mcus` — there is no `num_groups_per_mcu` parameter today. Adding it would be the single threading touchpoint for option A.

---

## §7. Findings beyond the inline checklist

The S2 step instruction's "Sprint 1 鎖定點清單" inline list (group count, group power, RelayMatrix shape, ModuleAssignment shape) covers the major axes. Two **non-obvious** hardcode assumptions surfaced during this audit that are *not* explicitly listed in any of those four:

1. **String-encoded group index in bridge relay node IDs** (`rectifier_board.py:97`):
   `node_a=f"MCU{prev_mcu}_G3"` hardcodes the *string* `"_G3"` — i.e., the bridge relay's left-side endpoint name embeds the literal group number `3` into the relay graph. This is observable in `RelayEventLog` output and any test that asserts on relay topology by string. It needs `f"MCU{prev_mcu}_G{num_groups_per_mcu - 1}"` for option A. Easy to forget because it's a string, not arithmetic.

2. **CSV column count in `vision_output.py:159`** (`row += ["OFF"] * 4`):
   The Timing Diagram CSV emits exactly 4 relay-state columns per MCU (`R1..R4` per the SPEC §17 schema). For option A this would need to grow with group count — but **the SPEC §17 schema would also need to change**, because the column names are baked into the spec. This is a documentation problem, not just a code problem.

Neither blocks option B. Both are footnotes that would surface during option A implementation; flagging here so they don't bite a Sprint 3 follow-up.
