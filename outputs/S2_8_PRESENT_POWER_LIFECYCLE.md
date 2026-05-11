# S2.8 Pre-Spike — `Vehicle.present_power_kw` Lifecycle

**Date:** 2026-05-11
**Scope:** Read-only trace of `Vehicle.present_power_kw` through the
FR-09 (single snapshot) and FR-14 (control-step generation) engine
paths, to confirm whether it is computed every tick and whether it
participates in any engine decision. Output is one new file
(`outputs/S2_8_PRESENT_POWER_LIFECYCLE.md`); no code, SPEC, test, or
comment touched.

**Baselines (unchanged at spike end):** 92 passed / 1 xfailed /
2 deselected; simulation 241 passed; FE tsc 0 errors.

---

## §1 — Method

Files read:
- `simulation/modules/vehicle.py` (full, 95 lines)
- `services/evcs-api/app/services/web_session_engine.py` (full, 425 lines — `create()`, `_settle_until_stable()`, `_log_engagement_state()`)
- `simulation/environment/simulation_engine.py` (full, 350 lines — `__init__`, `_run_sync`, `_driver_loop`, `_collect_snapshot`)
- `services/evcs-api/app/adapters/step_planner.py` L1-100 (module docstring + per-port `_phase_of` classifier)
- Targeted grep into `mcu_control.py` + `output.py` for `present_power_kw` consumers; read L210-241 (borrow / return trigger conditions)

Vocab note: the S2.8 vocab spike (`outputs/S2_8_VOCAB_SPIKE.md` §3)
referenced `Vehicle.update`. The actual method name is **`Vehicle.step(dt)`**
(`vehicle.py:58`). The vocab table's reference to "vehicle's per-tick
computed" was correct in concept but slightly off on the method name —
called out here in case the canonical table needs a tweak.

---

## §2 — Q1: Is `Vehicle.present_power_kw` recomputed every tick?

**Yes — every tick the vehicle is connected and not `COMPLETE`.**

Source `vehicle.py:58-84`:
```py
def step(self, dt: float) -> None:
    if self.output is None or self.state == VehicleState.COMPLETE:
        return                                             # short-circuit
    if self.state == VehicleState.IDLE:
        self.state = VehicleState.CHARGING
    # 1. Update SOC from previous step's power
    if self.present_power_kw > 0:
        delta_energy_kwh = self.present_power_kw * (dt / 3600.0)
        ...
    # 2. Check completion → zero present_power_kw and return
    # 3. Update max_require_power_kw from SOC curve
    # 4. Negotiate present power
    self.present_power_kw = min(
        self.max_require_power_kw, self.output.available_power_kw
    )
    self.output.present_power_kw = self.present_power_kw
```

The negotiation at L83 — `min(max_require, output.available)` — runs
unconditionally on each non-short-circuit `step()` call. The result is
also mirrored to `output.present_power_kw` (L84), which is what
downstream consumers read.

---

## §3 — Q2: In FR-09, does `WebSessionEngine.create()` reach Vehicle stepping?

**Yes — every settle tick calls `vehicle.step(dt)` for every vehicle.**

Path in `web_session_engine.py`:

1. `create()` (L138-155) → `cls(...)` constructs the instance and
   calls `_log_engagement_state()`. Then:
   ```py
   if any(p.max_required > 0 for p in instance._car_ports):
       await instance._settle_until_stable()
   ```
   Settle is skipped only when **all** ports request 0 kW (the
   "all-zero" fast path noted in the docstring at L122).

2. `_settle_until_stable()` (L216-249) runs up to
   `_CONVERGE_TIMEOUT_TICKS = 200` ticks. The per-tick body at
   L226-237 explicitly drives every vehicle:
   ```py
   for mcu in engine.mcu_controls:
       mcu._step_index = tc.step_index
   for vehicle in engine.vehicles:
       vehicle.step(dt)                                    # ← Q1 method
   engine._trigger_departures()
   done_events = [asyncio.Event() for _ in engine.mcu_controls]
   for mcu, ev in zip(engine.mcu_controls, done_events):
       await mcu.send(Tick(...))
   await asyncio.gather(*(e.wait() for e in done_events))
   ...
   engine.station.step(dt)
   tc.tick()
   ```

3. The vehicle list `engine.vehicles` is populated in
   `SimulationEngine.__init__` (L60-72) from
   `config.initial_vehicles`. `WebSessionEngine._build_simulation_config`
   (L163-193) creates one `InitialVehiclePlacement` per port with
   `max_required > 0`, so each active port contributes one vehicle to
   the settle loop. Ports with `max_required == 0` get no vehicle at
   all.

---

## §4 — Q3: Does `SimulationEngine` (legacy CLI path) also step vehicles?

**Yes — but the web service does not use this path.**

`SimulationEngine.run()` (L117-121) is the CLI/integration-test entry.
It dispatches to either `_run_sync` (single MCU, L125-145) or
`_run_async` → `_driver_loop` (multi MCU, L160-197). Both loop bodies
include the same `for vehicle in self.vehicles: vehicle.step(dt)`
line (L136-137 sync, L180-181 async). The legacy loop also calls
`_collect_snapshot` per tick to feed `VisionOutput`/CSV traces — the
web service skips this.

**Critically: `WebSessionEngine._settle_until_stable` reimplements the
per-tick body in-line rather than calling `SimulationEngine.run()`.**
The two paths share the same vehicle-step semantics but live in
different functions; any future change to the legacy loop would need
to be mirrored into `_settle_until_stable` (or vice versa).

---

## §5 — Q4: Is FR-14's engine loop the same as FR-09?

**Yes — FR-14 uses the same engine path, twice.**

`step_planner.py` module docstring (L1-9) describes the FR-14 flow:

> "The caller (`evcs_core_adapter.generate_control_steps`) supplies
> two already-converged `VisualSnapshot` instances — `initial_state`
> (built with `max_required = present`) and `final_state` (built with
> `max_required = target`)."

So FR-14 makes **two** `WebSessionEngine.create()` calls (one with
`max_required = port.present`, another with `max_required = port.target`),
each running its own settle. Both inherit the FR-09 path verbatim.
`step_planner` itself never calls `Vehicle.step` — it operates purely
on the two pre-converged snapshots, diffing relay states and
synthesising intermediate snapshots for FR-15 playback.

Per-port `_phase_of` classification (L71-80) reads only
`CarPortInput.present` / `CarPortInput.target` (the web-API user-input
scalars), **not** `Vehicle.present_power_kw`. No engine-internal field
crosses into the planner.

---

## §6 — Q5: Does `present_power_kw` influence settle convergence?

**Indirectly yes — it is the trigger source for SPEC §6.1 borrow.**

Settle's *break* condition (`_settle_until_stable` L238-244) is:
- relay-event-log length unchanged this tick **AND**
- `_all_pending_clear()` (no MCU has pending arrival/departure relay phases)

For `_consecutive_threshold` consecutive ticks. `present_power_kw`
does not appear directly in either check.

But `present_power_kw` lies on the **causal path that produces those
relay events during settle**:

- `Vehicle.step` writes `output.present_power_kw = min(max_require, available)` each tick.
- `MCUControl._tick_borrow_condition` (`mcu_control.py:210-226`) reads it:
  ```py
  present = output.present_power_kw
  available = output.available_power_kw
  if (present > 0
      and abs(present - available) < 0.01
      and vehicle.max_require_power_kw > available + 0.01):
      state.borrow_counter += 1
  else:
      state.borrow_counter = 0
  return state.borrow_counter >= self._consecutive_threshold
  ```
- When the counter hits the threshold (default 3), the MCU borrows a
  group → relay event → event_log length increases → settle's
  "no-new-events" counter resets.

So although `present_power_kw` does not gate the break, the loop would
**never reach steady state with any cross-MCU borrow** if
`present_power_kw` weren't computed each tick: the borrow counter
would stay stuck at 0 and `available_power_kw` would never grow past
the SPEC §11 minimum guarantee.

Return trigger (`_tick_return_condition`, L228-241) is slightly
different — it reads `vehicle.max_require_power_kw` directly, not
`present_power_kw`. So the borrow direction is `present`-driven, the
return direction is `max_require`-driven.

---

## §7 — Comparison matrix: FR-09 vs FR-14

| Aspect | FR-09 (snapshot) | FR-14 (control-step generation) |
|---|---|---|
| Engine entry point | `WebSessionEngine.create()` × 1 | `WebSessionEngine.create()` × 2 (one each for `present`, `target`) |
| Settle path | `_settle_until_stable()` | `_settle_until_stable()` (identical, called twice) |
| Per-tick `vehicle.step` calls | All vehicles (one per active port) | Same — twice, once per `create()` |
| `present_power_kw` recomputed per tick | Yes | Yes (in both `create()` calls) |
| `present_power_kw` consumed by | `MCUControl._tick_borrow_condition` (SPEC §6.1 borrow trigger) | Same — but only inside each engine's settle; the planner itself never reads it |
| Settle break condition | `event_log` unchanged + `_all_pending_clear` for 5 ticks | Same |
| Convergence depends on `present_power_kw`? | Indirectly yes (borrow trigger) | Indirectly yes (same) |
| Post-settle artifact | One `VisualSnapshot` | Two `VisualSnapshot`s, diffed by `step_planner.plan_transition` |
| `step_planner` reads `present_power_kw`? | n/a | **No** — reads only `CarPortInput.present` / `target` |
| `vehicle.update` (vocab spike's name) | Method is actually `vehicle.step` | Same |

**Verdict: the engine internals are identical between FR-09 and FR-14.
The only difference lives above the engine** — FR-14 invokes the same
machinery twice with different `max_required` substitutions, and then
runs a pure-snapshot diff in the step planner.

---

## §8 — Conclusion (descriptive only)

**`Vehicle.present_power_kw` is recomputed on every tick that the
vehicle is connected and not `COMPLETE`** (`vehicle.py:83`).
**`output.present_power_kw` (the mirrored field) is read every tick by
`MCUControl._tick_borrow_condition`** to evaluate the SPEC §6.1 borrow
trigger (`mcu_control.py:216`). FR-09 and FR-14 share an identical
engine loop (`WebSessionEngine._settle_until_stable`); FR-14 simply
runs the loop twice with different demand substitutions and diffs the
resulting snapshots in `step_planner`.

`present_power_kw` does not appear in the settle break predicate
directly, but it sits on the causal path that produces the relay
events the break predicate watches — without it, cross-MCU borrow
would never fire and settle would terminate at anchor-only
allocation.

No value judgements about correctness, design, or future Sprint
behaviour are made here.

---

## §9 — Vocab-canonical wording suggestion for SPRINT2_FINAL_STATUS §5

Current vocab spike §6 row 5 reads (paraphrased):
> `Vehicle.present_power_kw` — engine — float kW — per-tick;
> `= min(max_require, output.available_power_kw)` — SPEC §4.1 "Present Power"

Suggested replacement wording for the SPRINT2_FINAL_STATUS canonical
table (1-2 sentences):

> **`Vehicle.present_power_kw`** — engine — float kW. Recomputed every
> tick by `Vehicle.step(dt)` as `min(self.max_require_power_kw,
> self.output.available_power_kw)`; the result is also mirrored to
> `output.present_power_kw`, which `MCUControl._tick_borrow_condition`
> reads each tick to drive the SPEC §6.1 borrow counter. Used in both
> FR-09 and FR-14 engine paths (identical settle loop). Matches SPEC
> §4.1 "Present Power".

Optional addendum if a separate "consumer" column is added:

> Consumers: (1) `Vehicle.step` self-feedback (SOC integration on the
> next tick); (2) `MCUControl._tick_borrow_condition` via the
> mirrored `output.present_power_kw` field.

---

## §10 — Spike-session integrity

- No code, SPEC, test, or comment file modified.
- Only one new file: `outputs/S2_8_PRESENT_POWER_LIFECYCLE.md`
  (this report).
- No production / test execution.
- Baselines not re-run; expected unchanged because no source touched.
