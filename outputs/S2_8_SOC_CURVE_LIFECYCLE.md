# S2.8 Pre-Spike — `Vehicle.max_require_power_kw` SOC Curve Lifecycle

**Date:** 2026-05-11
**Scope:** Read-only trace of `Vehicle.max_require_power_kw`'s SOC
curve implementation: where the curve lives, what shape the web
service uses, and whether FR-09 and FR-14 share the same curve. One
new file: `outputs/S2_8_SOC_CURVE_LIFECYCLE.md`. No code / SPEC /
test / comment touched.

**Baselines (unchanged at spike end):** 92 passed / 1 xfailed /
2 deselected; simulation 241 passed; FE tsc 0 errors.

---

## §1 — Method

Files read:
- `simulation/modules/vehicle.py` (full, 95 lines)
- `simulation/utils/config_loader.py` L1-100 (`VehicleProfile`,
  `InitialVehiclePlacement`, `SimulationConfig`, `ConfigLoader.load_csv`,
  `_CSV_PATH`)
- `services/evcs-api/app/services/web_session_engine.py` L160-193 (already
  read in the prior lifecycle spike — `_flat_curve`,
  `_build_simulation_config`)
- `simulation/environment/simulation_engine.py` L60-72 (Vehicle
  construction from config — already read in prior spike)

Greps:
```bash
grep -rn "ev_curve_data\|ev_curve\|charge_curve\|soc_curve\|power_curve" \
     simulation/ services/ web/evcs-ui/src/ docs/
grep -rn "load_csv\|load_json\|ConfigLoader\|config_loader" \
     simulation/ services/ | grep -v config_loader.py:
ls associate/
```

No production / test execution.

---

## §2 — Q1: SOC curve implementation site

**Location:** `simulation/modules/vehicle.py`
- **Storage** (L25, L32): `Vehicle.__init__` accepts
  `soc_power_curve: list[tuple[float, float]]` and stores it sorted by
  SOC on `self.soc_power_curve`.
- **Interpolator** (L40-56): `Vehicle._interpolate_power(self, soc)`
  performs **linear interpolation** between the curve's breakpoints
  (clamps to first/last on either side of the SOC range).
- **Initial value** (L36): in `__init__`,
  `self.max_require_power_kw = self._interpolate_power(initial_soc)`.
- **Per-tick update** (L80, inside `step(dt)`):
  `self.max_require_power_kw = self._interpolate_power(self.current_soc)`.

**Signature:** Input = SOC % (float, clamped to [0, 100]); Output =
kW (float, the curve's interpolated y-value).

The `Vehicle` class is **curve-agnostic**: whatever (soc%, kw) tuple
list is passed at construction is what gets interpolated. The class
itself contains no hardcoded curve data.

---

## §3 — Q2: Curve type

Of the four candidate shapes the task brief lists:
- (A) hardcoded constant in `vehicle.py`,
- (B) flat per-port at user-input `max_required`,
- (C) real SOC-dependent interpolated curve (e.g. CSV-loaded Cybertruck),
- (D) external API / live lookup,

**The web service (FR-09 + FR-14) uses (B) — flat per-port, constructed
at engine-build time from each port's `max_required`.**

Evidence: `services/evcs-api/app/services/web_session_engine.py:160-161`
```py
@staticmethod
def _flat_curve(kw: int) -> List[Tuple[float, float]]:
    return [(0.0, float(kw)), (100.0, float(kw))]
```
Consumed at L171-175 in `_build_simulation_config`:
```py
profiles[port.port_id] = VehicleProfile(
    name=name,
    battery_capacity_kwh=_DEFAULT_BATTERY_KWH,
    soc_power_curve=self._flat_curve(kw),   # kw = port.max_required
)
```

Because both endpoints of the flat curve are `kw`, the interpolator
returns `kw` for any SOC value in [0, 100]. Effectively
`max_require_power_kw` is a **constant equal to the user's
`max_required` input** throughout the entire settle, regardless of
SOC progression.

Path (C) **also exists in the codebase** but lives entirely on the
CLI / demo side (see §6).

---

## §4 — Q3: Per-vehicle or global?

**Per-vehicle.** Each `Vehicle` instance owns its own `soc_power_curve`
attribute, populated at `__init__` from the caller's `VehicleProfile`.
No global / module-level curve table.

How the web service assigns curves:
- For each `CarPortInput` with `max_required > 0`,
  `_build_simulation_config` (L163-183) constructs one
  `VehicleProfile` named `f"web_port_{port.port_id}"` and one
  `InitialVehiclePlacement` pointing the profile at the matching
  `output_index = port.port_id - 1`.
- `SimulationEngine.__init__` (L60-72 — already read) loops over
  `config.initial_vehicles`, materialising a `Vehicle` per placement
  and connecting it to the right `Output`.
- Result: **one `Vehicle` per active port, each carrying a flat curve
  pinned to that port's `max_required` value**. Ports with
  `max_required == 0` get no `VehicleProfile` and no `Vehicle` at all.

---

## §5 — Q4: Do FR-09 and FR-14 share the same curve?

**Yes — identical mechanism, with FR-14 invoking it twice.**

- FR-09 path:
  `WebSessionEngine.create(system, ports)` → one
  `_build_simulation_config(ports)` → one set of flat curves built
  from `port.max_required`.
- FR-14 path (`step_planner.plan_transition` per the prior
  lifecycle spike §5): two `WebSessionEngine.create()` calls. The first
  passes `ports` rewritten so `max_required = present`; the second
  passes them rewritten so `max_required = target`. Each call goes
  through the same `_build_simulation_config` and the same
  `_flat_curve(kw)`, producing **independent** flat curves for the
  same Vehicle population.
- `step_planner` itself never touches `soc_power_curve` — it operates
  on the two pre-converged `VisualSnapshot`s.

**Verdict:** the *curve construction code* is shared verbatim; the
two FR-14 invocations produce two different flat values (one at
`present`, one at `target`), but both go through the same flat-curve
factory.

---

## §6 — Q5: `ev_curve_data.csv` — does it exist, and who reads it?

**Exists, but never reaches the web service.**

- **File:** `associate/ev_curve_data.csv` (`ls associate/` confirms).
- **Loader:** `simulation/utils/config_loader.py:38-39` defines
  `_CSV_PATH` pointing at it; `ConfigLoader.load_csv()` (L47-89)
  parses rows into `VehicleProfile(name, battery_capacity_kwh,
  soc_power_curve)` dict keyed by vehicle name (default: "2024 Tesla
  Cybertruck Cyberbeast (325 kW, optimized)").

### 6.1 Callers of `ConfigLoader.load_csv` (production grep)

```
simulation/utils/schedule_builder.py:31:    profiles = ConfigLoader.load_csv()
```
That is the **only** caller. `schedule_builder` feeds the CLI /
scenario runner.

### 6.2 Two-curve-system status

The codebase therefore has **two parallel curve providers**:

| Provider | Source data | Curve shape | Used by |
|---|---|---|---|
| `ConfigLoader.load_csv()` / `load_default()` | `associate/ev_curve_data.csv` | Real SOC-dependent (Cybertruck) | `simulation/utils/schedule_builder.py:31` (CLI/demo scheduler) |
| `WebSessionEngine._flat_curve(kw)` | User input `max_required` | Flat (`[(0, kw), (100, kw)]`) | All FR-09 + FR-14 paths |

The web service imports `VehicleProfile`, `InitialVehiclePlacement`,
and `SimulationConfig` directly from `config_loader` (L51-55 of
`web_session_engine.py`) — but does **not** import `ConfigLoader` or
call `load_csv` / `load_default` / `load_json`. So the CSV file is
inert from the web service's perspective; it would still load
correctly if the file went missing because no web code path opens
it.

This is **not dead code** in absolute terms (the schedule builder
still uses it for CLI demos / SPEC §16 scenarios), but it is dead
from the web service's perspective.

---

## §7 — Comparison matrix: web vs CLI curve paths

| Aspect | Web service (FR-09 / FR-14) | CLI / demo (`schedule_builder`) |
|---|---|---|
| Curve provider | `WebSessionEngine._flat_curve(kw)` | `ConfigLoader.load_csv()` |
| Curve data source | User-supplied `port.max_required` | `associate/ev_curve_data.csv` |
| Curve shape | Flat 2-point: `[(0, kw), (100, kw)]` | Real SOC-binned curve, sorted asc |
| `Vehicle._interpolate_power(soc)` returns | constant `kw` for any SOC | curve-driven, decreases past peak SOC |
| `max_require_power_kw` over a charging session | constant | curve-following (degrades as SOC climbs) |
| Per-vehicle curve? | Yes (one flat curve per active port) | Yes (one profile per vehicle, can be re-used across vehicles) |
| Sharing between FR-09 and FR-14 | Yes — same mechanism, FR-14 invokes twice (`present` then `target`) | n/a (CLI doesn't have FR-09/FR-14) |

---

## §8 — R1: Car 2 in this curve framework

(Descriptive only; no judgement on correctness.)

For Port 2 with `max_required = 75`:
1. `_build_simulation_config` creates a `VehicleProfile` with
   `soc_power_curve = [(0.0, 75.0), (100.0, 75.0)]`.
2. The `Vehicle` instance has `max_require_power_kw = 75` after
   `__init__` (initial SOC = 30) and **stays at 75 throughout the
   entire settle** because the flat curve makes `_interpolate_power`
   return 75 for any SOC.
3. During settle, `Vehicle.step` recomputes
   `present_power_kw = min(75, output.available_power_kw)` each tick.
4. The SPEC §11 engagement gate
   (`mcu_control.py:474` — prior vocab spike §5) raises
   `output.available_power_kw` to the per-Output minimum guarantee
   (125 kW for Port 2 under default `[50, 75, 75, 50]`) so the Output
   relay can close.
5. Borrow trigger condition (`mcu_control.py:218-222`, prior
   lifecycle spike §6) is:
   `present > 0 AND |present − available| < 0.01 AND max_require > available + 0.01`.
   With `present = 75`, `available = 125`, `max_require = 75`:
   `|75 − 125| = 50`, not less than 0.01 → trigger never fires → no
   borrow attempts.
6. Settle terminates at `available_power_kw = 125`, the snapshot
   reports `allocated_kw = 125` for Port 2, and `total_power_kw`
   counts 125.

The flat-curve fact is **not** the cause of the user-input-vs-allocated
mismatch (75 vs 125) — the SPEC §11 minimum guarantee gate is. But
the flat curve **does** mean the mismatch cannot self-correct over
time (a real SOC curve would also stay above 75 kW for the relevant
SOC range on a Cybertruck-class profile, so the same observation
would hold qualitatively).

---

## §9 — Conclusion (descriptive only)

The web service (FR-09 and FR-14) builds **flat per-port curves at
each port's user-input `max_required`**, via
`WebSessionEngine._flat_curve(kw)`. The `Vehicle` class is generic and
runs a linear interpolator (`_interpolate_power`), but the flat input
degenerates into a constant function. FR-09 and FR-14 share the
identical curve-construction code; FR-14 invokes it twice with
different `max_required` substitutions. `associate/ev_curve_data.csv`
+ `ConfigLoader.load_csv` exist and produce real Cybertruck curves,
but reach only `schedule_builder.py:31` (CLI / demo), never the web
service. No further opinion on whether this should change in
Sprint 2 / 3.

---

## §10 — Vocab-canonical wording suggestion for SPRINT2_FINAL_STATUS §5

For `Vehicle.max_require_power_kw` (1–2 sentences):

> **`Vehicle.max_require_power_kw`** — engine — float kW. Recomputed
> each tick by `Vehicle.step(dt)` via
> `self._interpolate_power(self.current_soc)` against the per-vehicle
> `soc_power_curve` set at construction. In FR-09 and FR-14 web
> paths, the curve is built by `WebSessionEngine._flat_curve(port.max_required)`
> (a flat 2-point list), so the value stays equal to the user-input
> `max_required` ceiling regardless of SOC progression. The
> CLI/demo path (`ConfigLoader.load_csv` → `associate/ev_curve_data.csv`)
> supplies real SOC-dependent curves but is not reached by any web
> code path.

---

## §11 — Spike-session integrity

- No code, SPEC, test, or comment file modified.
- Only one new file added by this spike:
  `outputs/S2_8_SOC_CURVE_LIFECYCLE.md`.
- No production / test execution.
- Baselines not re-run; expected unchanged because no source touched.
