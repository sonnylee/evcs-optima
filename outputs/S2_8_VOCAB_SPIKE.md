# S2.8 Pre-Spike — Vocabulary Catalogue

**Date:** 2026-05-11
**Scope:** Read-only research. Catalogues four overlapping concepts —
`max_required`, `present`, `available`, `output_min_guarantee_kw` —
across schemas, engine, and test code, so S2.8's step instructions
can use the existing terms correctly and not invent a sixth synonym.

**No code, SPEC, test, or comment edits.** Only this one new file.

---

## §1 — Method

Greps run (read-only):
1. `grep -rn "max_required" --include="*.py" --include="*.ts*"` → schemas, services, adapters, validation, FE.
2. `grep -rwn "present" --include="*.py"` → narrowed to schemas + step_planner + adapter + Vehicle.
3. `grep -rn "available_power\|engagement_avail" --include="*.py"` → simulation/ engine + web_session_engine.
4. `grep -rn "min_guarantee_for_output\|output_min_guarantee_kw" services/evcs-api/app/ simulation/` → all callers (production + test).

Files read in full or in narrow ranges:
- `services/evcs-api/app/schemas/car_port.py` (full)
- `simulation/modules/mcu_control.py` L22-46 (helper + module constants), L453-502 (gate `_advance_relay_phases`), L962-991 (`_sync_output`)
- `simulation/modules/vehicle.py` L36-93 (per-tick state + dict export)
- `simulation/hardware/output.py` L29 + L66 (`available_power_kw` field)
- `services/evcs-api/app/services/web_session_engine.py` L195-213 (`_log_engagement_state`)
- `services/evcs-api/app/adapters/step_planner.py` L60-78 (transition kind classification using `present`)
- `services/evcs-api/app/adapters/evcs_core_adapter.py` L51-84 (Present validity gate)
- Test caller listings via grep only (no full read).

---

## §2 — Q1: `max_required`

**Definition site:** `services/evcs-api/app/schemas/car_port.py:20`
```py
max_required: int = Field(..., ge=MAX_REQUIRED_MIN, le=MAX_REQUIRED_MAX)
```
- Constants: `MAX_REQUIRED_MIN = 0`, `MAX_REQUIRED_MAX = 600`
  (`app/constants.py`).
- Type: integer kW. Step alignment to 25 kW is enforced by the
  validator service (`normalize_car_port`), not the schema.

**Owner:** shared (backend Pydantic schema + FE form input —
`MaxRequiredField.tsx` writes via store → `PATCH /sessions`).

**Lifecycle:** user input. Persisted on the session and read on every
snapshot/Apply request.

**Semantics (one-liner):** the per-port ceiling the user is willing to
let the engine deliver. The settle loop tries to satisfy it but
clamps to capacity and to per-Output engagement constraints.

**Note:** matches SPEC §4.1's *Max Require Power* concept but is a
**user-declared** ceiling on the web-API side; the engine-side
counterpart (vehicle's actual demand) is `Vehicle.max_require_power_kw`
(see §6).

---

## §3 — Q2: `present`

**Definition site:** `services/evcs-api/app/schemas/car_port.py:21`
```py
present: int = Field(0, ge=MAX_REQUIRED_MIN, le=MAX_REQUIRED_MAX)
```
- Same `[0, 600]` range as `max_required`. Defaults to 0.

**Owner:** shared (BE schema + FE `PresentField.tsx`).

**Lifecycle:** user input, used **only** as the *starting state* of an
Apply transition (FR-14). The `present` field is **not** consumed
during snapshot computation for FR-09 — `WebSessionEngine` uses
`max_required` to drive the engine for both modes.

**Semantics (one-liner):** the user's declaration of what each port is
*currently* outputting; serves as the starting endpoint of the
Present→Target diff in `step_planner.plan_transition`.

**Distinction from engine-side `present_power_kw`:** SPEC §4.1's
*Present Power* concept is implemented on the *Vehicle* class as
`Vehicle.present_power_kw` (`simulation/modules/vehicle.py:37,83`),
computed each tick as `min(max_require_power_kw, output.available_power_kw)`.
The web-API `CarPortInput.present` is a **different value** — it is
the user's input scalar, not the engine's per-tick computed actual
output. They can disagree; `evcs_core_adapter._present_warnings`
(L51-84) flags such disagreements.

---

## §4 — Q3: `available`

The catalogue here is **two-headed** — one engine field, one
log-only label:

### 4a. `Output.available_power_kw` (the real field)
- **Definition site:** `simulation/hardware/output.py:29`
  ```py
  self.available_power_kw: float = sum(g.total_power_kw for g in groups)
  ```
- **Owner:** engine-only (Output hardware abstraction).
- **Type:** `float` kW.
- **Lifecycle:** per-tick. The canonical updater is
  `MCUControl._sync_output` (`mcu_control.py:962-991`) which **either
  zeros it (L968) or sets it to the live `total_power` of currently
  connected groups (L991)**. So this field reflects *currently
  deliverable* power based on which groups the borrow logic has
  attached, not a static maximum.
- **Read sites in production:** `mcu_control.py:169, 186, 217, 474`
  (the gate); also `Vehicle.update` reads it as the supply ceiling
  for `present_power_kw`.
- **Semantics (one-liner):** the engine's authoritative answer to
  "how much power can this Output actually deliver right now, given
  the currently connected SMR groups?".

### 4b. `engagement_avail` (a print-statement label only)
- **Definition site:** `services/evcs-api/app/services/web_session_engine.py:209`
  ```py
  f"engagement_avail={output.available_power_kw:>5.0f} kW, "
  ```
- This is **not a separate concept**. It is the same value as
  `Output.available_power_kw` rendered with a different name in a
  single debug `print(...)` inside `_log_engagement_state` ("post-
  arrival, pre-settle"). It does not exist as a variable, attribute,
  or function anywhere else.
- **Implication:** when the S2.4 stage-1 stdout showed
  `engagement_avail=125 kW` for Port 2, that was simply
  `output.available_power_kw` at the post-arrival snapshot moment.

---

## §5 — Q4: `output_min_guarantee_kw`

**Definition site:** `simulation/modules/mcu_control.py:28-38`
```py
def output_min_guarantee_kw(module_powers: list[int], output_local_idx: int) -> float:
    """SPEC §11 per-output minimum guarantee (kW).
    O0 anchors at G0 → guarantee = module_powers[0] + module_powers[1].
    O1 anchors at G3 → guarantee = module_powers[3] + module_powers[2].
    """
    if output_local_idx == 0:
        return float(module_powers[0] + module_powers[1])
    return float(module_powers[3] + module_powers[2])
```
- A **derived constant** per (board config, output index). Default
  `[50, 75, 75, 50]` yields **125 kW** for both outputs (the legacy
  hardcoded value referenced throughout S2.3.1 / S2.4 / S2.5
  reports).

**Callers — complete enumeration:**

| Caller | Production? | Site |
|---|---|---|
| `MCUControl._advance_relay_phases` gate | **Yes** | `mcu_control.py:473-474` — `if available_power_kw + 1e-9 >= min_guarantee: close output relay` |
| `test_web_session_engine.py:89` | test only | binds local `floor = output_min_guarantee_kw(...)` |
| `test_control_steps.py:146, 184` | test only | same `floor = ...` pattern |
| `tests/integration/test_engine_for_web_spike.py:216, 317` | test only | same `floor = ...` pattern |

**Production wiring status:** **wired, not dead**. The single
production caller is the SPEC §11 engagement gate inside
`_advance_relay_phases` — it is the authoritative place that decides
whether to close an Output relay this tick. (Earlier worry about
"dead helper" → resolved.)

**Semantics (one-liner):** the per-Output threshold that
`available_power_kw` must reach before the engine closes that
Output's relay; depends only on `module_powers` of the host REC BD,
not on user demand.

**Test-side variable name:** all four test files use the local name
`floor` for the helper's return value. So "floor" is a real variable
name **in tests**, but never appears in production code.

---

## §6 — Comparison Matrix

| # | Term | Source of truth (file:line) | Owner | Unit | Lifecycle | Synonyms found in code/comments |
|---|---|---|---|---|---|---|
| 1 | `CarPortInput.max_required` | `services/evcs-api/app/schemas/car_port.py:20` | shared (BE schema + FE form) | int kW [0, 600] | user input, session-persisted | `user_max` (web_session_engine print L208); SPEC §4.1 "Max Require Power" (conceptual) |
| 2 | `CarPortInput.present` | `services/evcs-api/app/schemas/car_port.py:21` | shared | int kW [0, 600] | user input; FR-14 transition START only | SPEC §4.1 "Present Power" (conceptual; *not* the same as Vehicle.present_power_kw) |
| 3 | `CarPortInput.target` | `services/evcs-api/app/schemas/car_port.py:22` | shared | int kW [0, 600] | user input; FR-14 transition END | none |
| 4 | `Vehicle.max_require_power_kw` | `simulation/modules/vehicle.py:36` | engine | float kW | per-tick; interpolated from SOC curve | SPEC §4.1 "Max Require Power" |
| 5 | `Vehicle.present_power_kw` | `simulation/modules/vehicle.py:37,83` | engine | float kW | per-tick; `= min(max_require, output.available_power_kw)` | SPEC §4.1 "Present Power" |
| 6 | `Output.available_power_kw` | `simulation/hardware/output.py:29` | engine | float kW | per-tick; mutated by `_sync_output` | `engagement_avail` (web_session_engine.py:209 print label only) |
| 7 | `output_min_guarantee_kw(...)` helper | `simulation/modules/mcu_control.py:28` | engine | float kW | derived constant per (config, output_idx) | `floor` (test-local var name in 4 files); SPEC §11 "per-output minimum guarantee" |
| 8 | `CarSnapshot.allocated_kw` | `simulation/.../snapshot schemas` (used in `evcs_core_adapter.py:82`) | engine→snapshot | int kW | per-snapshot output | sometimes loosely called "allocated" or "delivered" in test comments |

---

## §7 — Inference questions

### R1 — "Car 2 scenario" restated in catalogue terms

`CarPortInput.max_required = 75` for Port 2 (anchor at G3) is **less
than** `output_min_guarantee_kw([50,75,75,50], 1) = 125` (= 50 + 75
for the G3 anchor + G2 inner). The settle loop borrows groups until
`Output.available_power_kw ≥ 125 kW`; the gate at
`mcu_control.py:474` then closes the Output relay. The resulting
snapshot allocates 5 packs (= 125 kW = 50 + 75) to Port 2.

(Purely descriptive; no judgement on whether this behaviour is
correct — that's S2.8's call.)

### R2 — Where does the conversational word "floor" map?

**Mapping:** "floor" → `output_min_guarantee_kw(module_powers, output_local_idx)`.

Evidence:
- All 4 test files (§5 table) bind `floor = output_min_guarantee_kw(...)`
  at call sites — this is the only place the word appears in code.
- The helper's docstring header comment (`mcu_control.py:24-27`)
  itself says "the legacy hardcoded floor — but non-default configs
  differ", so the production code's own comment uses "floor" as a
  synonym for the helper's return value.

**Not a folk-only term:** "floor" has a precise mapping; it is the
return value of the SPEC §11 helper. The reason it has felt fuzzy in
prior reports is that "floor" was sometimes used loosely to also
mean *the engine's resulting `available_power_kw` after the gate
fires* (which equals the floor when borrow is min-borrow-only). Those
two values coincide in the simple case but are distinct concepts:
the floor is a **threshold**; `available_power_kw` is a **measured
runtime value**.

---

## §8 — Vocabulary recommendations for S2.8 drafting

### Use these (single-owner, unambiguous)

| When you mean… | Use |
|---|---|
| The user-declared per-port ceiling (web input) | `max_required` |
| The user-declared starting state of an Apply transition | `present` |
| The user-declared target state of an Apply transition | `target` |
| The engine's per-tick deliverable power for an Output | `Output.available_power_kw` (or "available power" prose) |
| The SPEC §11 threshold that gates output-relay close | `output_min_guarantee_kw(…)` (or "min guarantee" prose) |
| The vehicle's per-tick computed actual draw | `Vehicle.present_power_kw` (always qualify with "vehicle" prefix) |
| The vehicle's curve-driven instantaneous demand | `Vehicle.max_require_power_kw` (always qualify) |
| The snapshot's reported allocation per port | `CarSnapshot.allocated_kw` |

### Avoid these (ambiguous or confusing)

| Word | Why to avoid | Use instead |
|---|---|---|
| **"floor"** | Precise mapping exists (see R2) but has been used loosely for both the threshold *and* the resulting `available_power_kw`. In step instructions, write `output_min_guarantee_kw(...)` or "SPEC §11 minimum guarantee" explicitly. | `output_min_guarantee_kw` / "min guarantee" |
| **"engagement_avail"** | Print-label only; not a real variable. Saying it in spec text suggests it's a concept worth tracking. | `Output.available_power_kw` |
| **bare "present"** without a qualifier | Two distinct things: web-API `CarPortInput.present` (user input scalar) and engine `Vehicle.present_power_kw` (per-tick computed). | qualify: "user-input present" vs "vehicle present power" |
| **bare "available"** without a qualifier | Easy to confuse with "minimum guarantee" in casual reading. | `Output.available_power_kw` (full attribute name) |
| **"engagement_avail >= floor" shorthand** | Both terms problematic per above. | `output.available_power_kw >= output_min_guarantee_kw(…)` (full predicate) |

### Naming policy for any new variable S2.8 introduces

- Backend / engine variables holding *power-in-kW* values must end
  with `_kw` (matches existing `available_power_kw`,
  `present_power_kw`, `max_require_power_kw`).
- Functions returning the §5 helper-style derived constant must
  include the word `min_guarantee` (matches existing
  `output_min_guarantee_kw`).
- Web-API user-input fields use bare `present` / `target` /
  `max_required` (no `_kw`) to match the existing
  `CarPortInput` schema.
- If S2.8 introduces a *new* concept, define it once in
  `app/constants.py` or `mcu_control.py`'s module preamble and
  cross-reference from anywhere it's used.

---

## §9 — Spike-session integrity

- No code, SPEC, test, or comment file modified.
- Only one new file: `outputs/S2_8_VOCAB_SPIKE.md` (this report).
- No production code or test execution during the spike.
- Baselines (FE tsc 0, BE 92 passed / 1 xfailed, simulation 241
  passed) not re-run; expected unchanged because no source touched.
