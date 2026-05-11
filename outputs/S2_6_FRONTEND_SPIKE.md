# S2.6 Frontend Spike — Catalogue

**Date:** 2026-05-11
**Scope:** Read-only assessment of `web/evcs-ui/` config panel + Apply
call chain to scope S2.6 (FR-10 / FR-11 dynamic config). No code or
docs touched.

**Baseline checkpoint** (from prior turn, unchanged at spike end):
- `tests/` (simulation): `241 passed`
- `services/evcs-api/tests`: `92 passed, 1 xfailed, 2 deselected`
- Frontend tsc: 0 errors

---

## §1 — Method

Files read (paths absolute under `/workspaces/evcs-optima/`):

| Layer | File |
|---|---|
| FE config panel | `web/evcs-ui/src/components/config-panel/ConfigPanel.tsx` |
| FE config inputs (unmounted) | `…/config-panel/RecBdCountInput.tsx`, `…/ModulePowerInput.tsx` |
| FE store | `web/evcs-ui/src/stores/evcsStore.ts` |
| FE API wrapper | `web/evcs-ui/src/api/evcsApiClient.ts` |
| FE app shell | `web/evcs-ui/src/components/App.tsx` |
| FE topology consumers | `…/topology/{TopologyView,RecBdLabel,PackGrid}.tsx` (grep) |
| FE validation utils | `web/evcs-ui/src/utils/validation.ts` |
| BE config schema | `services/evcs-api/app/schemas/config.py` |
| BE session schema | `services/evcs-api/app/schemas/session.py` |
| BE sessions route | `services/evcs-api/app/api/v1/sessions.py` |
| BE validation route | `services/evcs-api/app/api/v1/validation.py` |
| BE palette route | `services/evcs-api/app/api/v1/palette.py` |
| BE config service | `services/evcs-api/app/services/config_service.py` (head + grep) |
| BE snapshot schema | `services/evcs-api/app/schemas/snapshot.py` (grep `color`) |

No build / test / dev server invocations.

---

## §2 — Q1: ConfigPanel state of play

`web/evcs-ui/src/components/config-panel/ConfigPanel.tsx` is a
**Sprint-1 placeholder shell** — it does not read user input.

Hardcoded constants at the top of the file (L4–L6):
```ts
const SPRINT1_REC_BD_COUNT = 4;
const SPRINT1_MODULE_POWERS = [50, 75, 75, 50];
```

What's wired vs. what's faked:
- Reads `systemConfig` from the store (L9), so display values reflect
  whatever the session currently holds.
- Renders **two `<ReadOnlyField>` placeholders** (L36–46) with the note
  "動態 REC BD 配置 Sprint 2 上線" / "動態 module power 配置 Sprint 2
  上線". Both inputs are `disabled readOnly`.
- The `Apply` button (`onApply`, L19–28) **always sends the same
  hardcoded `[50,75,75,50] × 4`** payload regardless of current store
  state. It does not read from the read-only fields and does not honor
  any user edit.
- The summary rows ("總容量" / "總充電槍數" / "硬體拓撲預覽")
  *do* compute from the live store config (L13–17), so if a session
  were initialised with a different config they would render correctly
  — only the inputs and `onApply` are frozen to defaults.

**One-liner:** ConfigPanel is a display-only shim — REC BD count and
module powers are hardcoded constants, and `onApply` ships exactly
those constants regardless of UI state.

---

## §3 — Q2: RecBdCountInput

`web/evcs-ui/src/components/config-panel/RecBdCountInput.tsx` exists
(40 lines), is fully written, and **is not mounted anywhere** —
header comment L1 explicitly says "Sprint 1: not currently mounted —
ConfigPanel uses ReadOnlyField placeholders. Sprint 2 (FR-10):
re-mount this for dynamic REC BD count."

Props match the planned shape: `{ value: number; onChange: (next:
number) => void }`. Imports `REC_BD_MIN`/`REC_BD_MAX` (1 / 12) from
`utils/validation.ts`. Renders a `<input type="number">` with the
correct range, bad-input red ring, and a helper line describing the
2-Car-Port-per-REC-BD relationship.

Backend alignment check:
- BE `RecBdConfig` validator (`schemas/config.py:48`) caps `rec_bd_count`
  at `REC_BD_MAX = 12`, matching the FE constant.
- The component does not call any API itself — it's purely a controlled
  input. Whatever wraps it must call `evcsApi.validateSystemConfig`
  (already in the API client).

**One-liner:** Component is Sprint-2-ready, props match the planned
contract, and `REC_BD_MIN/MAX` align with backend; just needs to be
mounted and wired into ConfigPanel state.

---

## §4 — Q3: ModulePowerInput

`web/evcs-ui/src/components/config-panel/ModulePowerInput.tsx` exists
(67 lines), is fully written, and **is not mounted** (same Sprint-2
header comment as §3).

What it does already:
- Controlled `<input type="text">` with debounced (`useDebounce`,
  400 ms) calls to `evcsApi.validateModulePowers(raw)`.
- On parse success, surfaces `powers.length`, `total_capacity_kw`, and
  `pack_count` from the backend response. On parse error, surfaces
  per-error messages with red styling.
- Calls `onParsed(recBdId, parsed)` to bubble parsed result to the
  parent.

Props: `{ recBdId: number; initialRaw: string; onParsed: (recBdId,
parsed: ModulePowerStringResponse) => void }`.

Backend alignment:
- `POST /api/v1/validate/module-powers` returns
  `ModulePowerStringResponse { powers, total_capacity_kw, pack_count,
  errors }` — exact match to the type the FE imports from `types/evcs`.

**One-liner:** Component is Sprint-2-ready including async backend
validation and error display; same mounting gap as §3.

---

## §5 — Q5: Store action `updateSystemConfig`

`web/evcs-ui/src/stores/evcsStore.ts:115-165`. Already wired for
dynamic config — no Sprint-1 hardcoding inside the store.

Flow when called:
1. Refuses if `mode === 'player'` (FR-15 separation).
2. Calls `evcsApi.validateSystemConfig(cfg)` first; on validation errors
   stops and writes them to `configErrors`.
3. **REC BD count change → drops priorities** (`defaultPortsForCount`
   at L137 vs. priority-clear-only at L139). This satisfies FR-10's
   spec note "REC BD 數量變更導致 N 改變 → 現有優先級設定清除".
4. If no `sessionId` yet → `initSession(cfg, nextPorts)`; otherwise
   `evcsApi.patchSession(sid, { system_config: cfg, car_ports:
   nextPorts })`.
5. Writes server response back into store, then calls
   `refreshSnapshot()`.

**One-liner:** `updateSystemConfig` already accepts arbitrary
`SystemConfig` payloads end-to-end; the bottleneck is the UI
(ConfigPanel doesn't construct anything other than the hardcoded
constants).

---

## §6 — Q4: Apply call chain (end-to-end)

| # | Layer | File:Line | Symbol |
|---|---|---|---|
| 1 | UI button | `web/evcs-ui/src/components/config-panel/ConfigPanel.tsx:67-74` | `<button onClick={onApply}>` |
| 2 | Local handler | `…/ConfigPanel.tsx:19-28` | `onApply` (builds hardcoded `cfg`) |
| 3 | Store action | `web/evcs-ui/src/stores/evcsStore.ts:115-165` | `updateSystemConfig(cfg)` |
| 4a | API wrapper (validate) | `web/evcs-ui/src/api/evcsApiClient.ts:41-42` | `evcsApi.validateSystemConfig(cfg)` |
| 4b | BE validate route | `services/evcs-api/app/api/v1/validation.py:109-123` | `POST /validate/system-config` |
| 5a | API wrapper (PATCH) | `…/evcsApiClient.ts:47-51` | `evcsApi.patchSession(sid, { system_config, car_ports })` |
| 5b | BE PATCH route | `services/evcs-api/app/api/v1/sessions.py:36-49` | `update_session` |
| 5c | BE service | (called from route) | `SessionStore.update(...)` |
| 6 | Snapshot refresh | `…/evcsStore.ts:215-224` | `refreshSnapshot()` → `evcsApi.getSnapshot(sid)` → `GET /sessions/{id}/snapshot` |

Initial-session branch (no `sessionId` yet) takes
`updateSystemConfig` → `initSession` (`evcsStore.ts:92-113`) →
`evcsApi.createSession` (`POST /sessions`) before the PATCH path.

**One-liner:** 6 layers (button → handler → store action → validate
+ patch APIs → backend route+service → snapshot refresh); chain is
fully wired and unmodified by Sprint 1 — only the *payload* is
frozen.

---

## §7 — Q6: Existing Vitest coverage

`find /workspaces/evcs-optima/web/evcs-ui -name "*.test.*" -o -name
"*.spec.*"` returns **zero matches** (excluding `node_modules` /
`dist`). The `web/evcs-ui/tests/` directory exists but contains only
nested `components/` and `stores/` empty-or-near-empty placeholders;
no test files.

Implication: there is no Vitest baseline to preserve or expand. S2.6
work cannot regress UI tests because none exist.

**One-liner:** 0 frontend tests; whatever S2.6 adds is greenfield, so
"frontend baseline must hold" reduces to "tsc 0 errors" only.

---

## §8 — Q7: Backend schema alignment

Backend `SystemConfig` (`services/evcs-api/app/schemas/config.py`):

| Field | Type | Constraint |
|---|---|---|
| `rec_bd_count` | `int` | `[REC_BD_MIN, REC_BD_MAX]` = `[1, 12]` |
| `rec_bds` | `List[RecBdConfig]` | length must equal `rec_bd_count`; ids must be `1..N` in order |
| `RecBdConfig.id` | `int >= 1` | per-board id |
| `RecBdConfig.module_powers` | `List[int]` | each ∈ `[POWER_MIN_PER_MODULE=50, POWER_MAX_PER_MODULE=100]`, multiple of `STEP_KW=25`, length ≥ 1 |

Frontend `SystemConfig` type comes from generated
`web/evcs-ui/src/api/schema.ts` (re-exported via `types/evcs.ts`), so
the **structural schema is in lockstep** by construction (regen via
`bun run gen:api`).

Frontend mirror constants in `web/evcs-ui/src/utils/validation.ts`:
- `REC_BD_MIN = 1`, `REC_BD_MAX = 12` ✅ matches BE
- `POWER_MIN_PER_MODULE = 50`, `POWER_MAX_PER_MODULE = 100` ✅ matches BE
- `STEP_KW = 25` ✅ matches BE

Validate endpoints already exist and the FE wrapper already calls them:
- `POST /validate/module-powers` → returns parsed powers + capacity +
  pack count + errors. FE `ModulePowerInput` already consumes this.
- `POST /validate/system-config` → returns errors + capacity +
  car_port_count. FE `updateSystemConfig` already calls this.

One asymmetry to flag for S2.6:
- **`RecBdConfig.module_powers` does not require a fixed length of 4**
  on either side — backend accepts `length ≥ 1`. ConfigPanel's
  `modulePowers.length` substitution at L63 will render that count
  correctly (e.g. "3 Groups" for `[50,75,75]`), but the topology view
  and the simulation core were locked to 4 groups per MCU during
  Sprint 1. **Per S2.5/S2.4 production-engine work, the engine now
  honors arbitrary group counts**, but there is no spike evidence in
  this read-only assessment that the FE topology grid renders
  correctly for `≠4` groups — it should be visually verified.

**One-liner:** Schema, constants, and validate endpoints fully aligned;
the only seam is FE topology rendering for non-4-group configs (visual
verification needed, not a schema gap).

---

## §9 — Q8: Palette cycle (FR-10 4-color cycle)

Backend status: **fully implemented**.

- `services/evcs-api/app/services/config_service.py:32-37` —
  `pick_palette(count, cycle=True)` returns either
  `DEFAULT_PALETTE_CYCLE[i % 4]` or `EXTENDED_PALETTE[i % N]`.
- `GET /api/v1/palette?count=N&cycle=true|false`
  (`services/evcs-api/app/api/v1/palette.py`) returns
  `{ rec_bd_colors, cycle, count, full_cycle, extended, semantic{...} }`.
- `pick_palette` is also called inside
  `build_topology` (line 85) and is used by the snapshot service to
  populate `RecBdSnapshot.color` / `PackSnapshot.color` /
  `RelaySnapshot.color` / `CarSnapshot.color`. All four snapshot
  schemas have `color: str` fields
  (`services/evcs-api/app/schemas/snapshot.py:13-51`).

Frontend status: **consumes backend colors directly, no UI toggle**.

- Topology components read `color` straight off snapshot objects
  (`RecBdLabel.tsx:22,47`, `TopologyView.tsx:18,98`, `PackGrid.tsx:16`).
- `evcsApi.getPalette` exists in the client wrapper
  (`evcsApiClient.ts:30-33`) and the generated schema has the `cycle`
  query param (`schema.ts:679,796-797`), but **`grep -rn "getPalette"
  src/` shows no caller** — no component or hook invokes it. Cycle
  preference is therefore implicit (`cycle=True` default on the
  backend).

**One-liner:** Backend cycle/extended palette is end-to-end ready and
already paints the snapshot; FE just needs a UI affordance if S2.6 wants
to expose the toggle (FR-10 spec wording allows the cycle to be the
locked default → no toggle is also defensible).

---

## §10 — S2.6 expected file scope + effort

Based on §2–§9, the minimum viable S2.6 (mount the two existing inputs
and replace `onApply`'s hardcoded payload with state-driven values):

| File | Change | Sketch | Est. |
|---|---|---|---|
| `web/evcs-ui/src/components/config-panel/ConfigPanel.tsx` | Replace two `ReadOnlyField` placeholders with mounted `<RecBdCountInput>` + N × `<ModulePowerInput>`; introduce local draft state (`draftCount`, `draftRawByBd`); rebuild `onApply` from draft state instead of hardcoded constants | ~80 LOC delta (rewrite of L8-77) | ~1.5 h |
| `web/evcs-ui/src/components/config-panel/RecBdCountInput.tsx` | Delete the `// not currently mounted` header comment; no behavioural change unless you want a "+/-" affordance | ~3 LOC | trivial |
| `web/evcs-ui/src/components/config-panel/ModulePowerInput.tsx` | Same — strip stale comment | ~2 LOC | trivial |
| (optional) `…/components/shared/` | A small "REC BD count change wipes priorities" confirmation modal/banner — store action already does the wipe, but the SPEC asks for an explicit warning UX | new component, ~30 LOC | ~30 min if pursued |
| (optional) `…/components/topology/TopologyView.tsx` or palette toggle in ConfigPanel | Visual sanity for non-4-module configs + optional palette `cycle=false` toggle | depends on §11 risk #1 outcome | 0–1 h |

**No backend changes**, **no SPEC changes**, **no Vitest changes**
(none exist). Total est.: **~2 h baseline; ~3.5 h with both
optionals**.

---

## §11 — Risks for S2.6

1. **Topology grid hard-assumes 4 groups per MCU.** Backend engine
   accepts variable `module_powers.length` and the snapshot returns
   per-pack data, but `TopologyView.tsx` was developed against the
   default `[50,75,75,50]`. If S2.6 lets users pick e.g. 3 or 5
   groups, layout may break (column count, inter-group relay count
   per row at L97 derives `sortedInter` based on snapshot data — this
   should adapt, but should be visually verified at length 3 and
   length 5 before claiming FR-11 done). **Likelihood:** medium.
   **Impact:** rendering breakage that bypasses tsc/lint.
2. **`ModulePowerInput` debounce + validate fires per keystroke (after
   400 ms idle).** Mounting N copies (up to 12 for FR-10 max) means
   simultaneous updates spawn N HTTP calls. Backend is fast, but the
   user can hammer the panel while typing. **Likelihood:** low.
   **Impact:** flaky UX during rapid edits, but no data corruption
   (debounce + abort-on-cleanup already wired at L24-33).
3. **REC BD count drop wipes priorities silently in current store
   action.** SPEC FR-16 wording asks for a confirmation step
   ("警告 modal 確認後執行"). Current `updateSystemConfig` zeroes
   priorities without UI warning. S2.6 should add at least an inline
   warning row in `ConfigPanel`. **Likelihood:** high.
   **Impact:** spec compliance gap, easy to land but easy to forget.
4. **`onApply` always issues both `validateSystemConfig` and
   `patchSession`.** When user clicks Apply with no actual change,
   we still pay two HTTP round-trips and a snapshot refresh.
   Acceptable for S2.6 (FR-10 doesn't demand idempotence
   short-circuit) but worth noting if perf creeps. **Likelihood:**
   low. **Impact:** UX nit only.
5. **No Vitest coverage means S2.6 cannot regress what doesn't exist,
   but also means the visual + interaction guarantees are tsc-only.**
   Any UX regression in ConfigPanel will land silently. Optional:
   add a single Vitest happy-path test for `ConfigPanel` (mount with
   stub store, click Apply, assert payload matches state). Not a
   blocker. **Likelihood:** medium that something silent slips.
   **Impact:** depends on QA discipline.

**Largest risk** is #1 (topology rendering for non-4-module
configurations) — it crosses the FE/BE seam and is the only one tsc
can't catch.

---

## §12 — Spike-session integrity

- No code, doc, SPEC, or test file modified.
- Only one new file: `outputs/S2_6_FRONTEND_SPIKE.md` (this report).
- No build / dev server / pytest / vitest / tsc invocation during
  the spike (the tsc check from the prior turn is a baseline reference,
  not a spike action).
- `git status` should show exactly 1 untracked file: this report.
