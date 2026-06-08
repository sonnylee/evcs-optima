# SPIKE-XMCU-REPORT — Cross-MCU departure leaves lender relay orphaned-CLOSED

> Read-only spike. **No production code changed.** Root cause: a cross-MCU
> **borrower's departure** clears the lender's `ModuleAssignment` mirror but
> never tells the lender to resync its relays, leaving the lender's inter-group
> relay **orphaned-CLOSED**. Caught by the F1 exploration harness's A1 check.

## ⚠️ Pre-flight: the "DC <5A hot-switching" question (A.2 / DP-2)

`grep -rni 'current|5a|hot.?switch|amp' simulation/` returns **nothing**
relay-related — the only `<5` hits are module-power validation
(`rectifier_board.py:56`, `p < 50`) and CSV row length (`config_loader.py:58`).
**There is no current / 5A / hot-switching logic anywhere in production.**
`Relay.switch()` is an unconditional state toggle + event-log append. This
matches the prior ruling that "DC ≥5A hot-switching" is a debunked phantom
requirement. **All DP-2 "current<5A" sub-questions are therefore "N/A — no such
constraint exists in code"**; ordering is reasoned purely on SPEC §11 sequencing
+ fast-toggle races.

---

## A.1 — Code citations (current line numbers; header drift corrected)

Header said *resync `:864-877`, arrival 3-phase `:560-600`*. Actual:
`_apply_global_relay_state` is **832-895** (open loop **873-877**, close
**886-895**); arrival `pending_intergroup_close=1` set at **582**, phase machine
**440-494**. Corrected below.

**`_try_return_async` — cross-MCU return (borrower side), the CORRECT resync path (299-330)**
```
312            if target == state.interval_min:
313                state.interval_min = target + 1
314            else:
315                state.interval_max = target - 1
319            await send_return_notify(                       # ← notifies lender
320                neighbor, self._mcu_id, target_phys, self._step_index,
321            )
325            self._apply_global_relay_state()                # borrower's own relays
327            self._ma.release(output_idx, target_phys)
328            self._mirror_release(output_idx, target_phys)
```

**`_handle_return_notify` — lender side; clears MA **and** resyncs its own relays (399-410)**
```
406        owner = self._ma.get_owner(msg.group_idx)
407        if owner is not None:
408            self._ma.release(owner, msg.group_idx)
409            self._sync_foreign_relays(msg.step_index)        # ← lender relay resync
410        msg.response.set_result(True)
```

**`_sync_foreign_relays` (826-830)**
```
826    def _sync_foreign_relays(self, step_index: int) -> None:
829        self._step_index = step_index
830        self._apply_global_relay_state(include_output=False)
```

**`_apply_global_relay_state` (832-895) — central reconciler; reconciles relays
to `needed` (intervals + foreign-borrow spans).**
Callers: `__init__:138`, `_try_borrow_async:296`, `_try_return_async:325`,
`_apply_borrow:355`, `_apply_return:365`, arrival phase `:450`,
`_force_return_group:742`, `_sync_foreign_relays:830`.
```
845        foreign_seen: set[int] = set()                       # ← honours OTHER borrowers
846        for g in range(self._group_base, self._group_base + GROUPS_PER_MCU):
847            owner = self._ma.get_owner(g)
...
873        for r in all_relays:                                 # OPEN any CLOSED ∉ needed
874            if r.state == RelayState.CLOSED and r not in needed:
877                r.switch(self._step_index)                   # (no current gating)
886        for r in needed_sorted:  # close inter-group/bridge first (886-890), output last (891-895)
```

**`_finalize_departure` (645-674) — the BUG SITE: releases foreign groups via
`_mirror_release`, never notifies the lender**
```
656        r = self._board.output_relays[output_local_idx]
657        if r.state == RelayState.CLOSED:
658            r.switch(self._step_index)                       # open OWN output relay
660        if state.interval_min is not None:
661            for g_virt in range(state.interval_min, state.interval_max + 1):
662                g_phys = self._wrap(g_virt)
663                if self._ma.get_owner(g_phys) == output_idx:
664                    self._ma.release(output_idx, g_phys)
665                    self._mirror_release(output_idx, g_phys)  # ← clears lender MA, NO resync
673        self._board.outputs[output_local_idx].disconnect_vehicle()
674        self._sync_output(output_local_idx)
```

**`_mirror_release` (379-381) — direct cross-board MA mutation, no message, no relay touch**
```
379    def _mirror_release(self, abs_o: int, abs_g: int) -> None:
380        if self._station is not None:
381            self._station.release_across_window(abs_o, abs_g)   # iterates ALL boards' MA only
```

**`_open_departure_intergroup_relays` (599-643) — opens only `departing − still_needed`
of **self's own** relays (preserves foreign spans 618-636); never touches a
lender's relays.**

---

## A.2 — Cross-MCU communication map

- **`ReturnNotify` is an async actor message (queue + Future RPC), not
  shared-state mutation.** Send: `send_return_notify` (`return_protocol.py:13-33`)
  → `neighbor.send(ReturnNotify(...))` → `await fut`. Receive: `Actor.handle`
  (`mcu_control.py:147-148`) → `_handle_return_notify` (399-410) →
  `msg.response.set_result(...)`. **Only the owning (lender) MCU switches its own
  relays** (SPEC §11) — this is exactly why the handshake exists.
- **`_mirror_release` mutates shared state directly** (`station.release_across_window`
  → every board's MA), sends **no** message, and triggers **no** relay
  re-evaluation. The lender re-evaluates relays **only** when *its own*
  `_apply_global_relay_state` runs — i.e. on its own borrow/return/arrival/
  departure/force-return, or on receiving `BorrowRequest`/`ReturnNotify`
  (`→_sync_foreign_relays`). **A departing borrower's `_mirror_release` triggers
  none of these on the lender → the gap.**
- **`_apply_global_relay_state` is not a settle-loop construct** — it's a
  synchronous full-reconciliation invoked at each relay-affecting decision point.
  **No DC/current/5A/hot-switching gating exists**; the only protections are
  SPEC §11 ordering (open-not-needed → close inter-group → close output) and
  idempotent reconciliation from current ownership.

---

## A.3 — Decision points

### DP-1 — Fix surface → **Recommend α, refined: reuse the existing `ReturnNotify` send (not a new message, not the whole `_try_return_async`)**

`_handle_return_notify` already does *exactly* the needed lender action (clear MA
+ `_sync_foreign_relays`). So:
- **α (recommended, refined):** In `_finalize_departure`, for each group
  physically owned by a **foreign** MCU, `await send_return_notify(lender, …)`
  instead of `_mirror_release`; keep local-group release as-is. Single source of
  truth, ownership-correct (lender switches its own relays), **no new message**.
  *Con:* `_finalize_departure`/the departure phase must run in an async context
  to await — a real refactor (see Phase B).
- **β (acceptable, rejected as redundant):** a new `DepartureNotify` + handler
  would be byte-for-byte the same as `_handle_return_notify` → gratuitous
  duplication.
- **γ (rejected):** calling `_apply_global_relay_state` from inside
  `_mirror_release` runs in the **borrower's** context reaching into the
  **lender's** relays — violates SPEC §11 "only the owning MCU switches its own
  relays" and breaks actor isolation; also `_mirror_release` is shared by
  borrow/return/force-return where relays are already handled → double-resync
  risk.

### DP-2 — Ordering

Insert the lender notify **inside the release loop (661-665), replacing
`_mirror_release` for foreign groups**, after the departing output's own relays
are already open (they were opened a phase earlier in
`_open_departure_intergroup_relays`, and the output relay at 658). **No DC/5A
concern (none exists).** Real concerns, both satisfied: (1) SPEC §11
inter-group-before-output is already enforced by the 3-phase machine *before*
`_finalize_departure`; (2) **no fast-toggle race** — `_sync_foreign_relays`
recomputes `needed` from the lender's *current* ownership, so it only opens
relays no longer needed by anyone (idempotent), never closes-then-opens.

### DP-3 — Boundary sanity (all correct under α)

1. **One lender, multiple borrowers, partial departure:**
   `_apply_global_relay_state`'s `foreign_seen` loop (845-863) recomputes
   `needed` over *all* current foreign owners, so resync keeps relays still
   needed by the remaining borrower. ✓
2. **Lender's own output departs while also lending:**
   `_open_departure_intergroup_relays` preserves `still_needed` incl. foreign
   spans (618-636) → won't yank a relay a foreign borrower still needs. ✓
3. **3-MCU window / 2-hop:** borrow is local-first then crosses to **one**
   immediate neighbor (right>left); the 3-MCU MA window + bridge-only
   `_compute_required_relays` mean a borrow can't span 2 hops, so the lender is
   always an immediate neighbor reachable via the same
   `_neighbor_by_mcu_id`/`_get_neighbor_for_group` the borrow used. **Phase B
   must assert lender-is-immediate-neighbor** (defensive; drop notify safely if
   `None`). ✓ (pending that assertion)

### DP-4 — Validation gap → **Recommend (c): lightweight in production + comprehensive in the harness**

The harness's A1 (`relay_invariants.relay_ownership_violations`) already catches
this — that's how it surfaced. Recommend **(c)**: add a *lightweight* relay↔MA
consistency assertion (the A1 invariant "inter-group CLOSED ⟺ co-owned", with the
A3 pristine-init exception) into production `Validator.check`/
`ChargingStation.validate` as part of the Phase B fix — O(relays), guards the fix
against regression across the existing 241-test suite + web layer immediately —
**and** keep the exploration A1 as the exhaustive cold-config net. (a)-only
defers protection; (b)-only loses the broad sweep.

---

## Phase B — estimated touched files & diff size

| File | Change | ~LoC |
|---|---|---|
| `simulation/modules/mcu_control.py` | `_finalize_departure`: notify lender (`send_return_notify`) for foreign groups; thread async into the departure phase (the real cost — `_advance_relay_phases`/`_pre_step_guard` are currently sync; cross-MCU only in async path, so either make the departure finalize awaitable or defer foreign-notifies to the async `_handle_tick` context) | **30–60** |
| `simulation/utils/validator.py` *(DP-4c)* | lightweight relay↔MA consistency check + A3 pristine exception | **20–30** |
| `tests/integration/test_cross_mcu_relay_sync.py` | +1–2 regression tests (cross-MCU borrow → borrower departs → assert lender relay reopens); fixture `make_3mcu_system` exists | **40–60** |
| Baseline | 241 sim tests + 92 api tests must stay green | — |

**Primary risk/complexity:** threading the `await send_return_notify` into the
synchronous departure phase machine without disturbing the single-MCU sync path
(which has no foreign borrows). Recommend collecting foreign-group releases
during `_finalize_departure` and awaiting their notifies from the async
`_handle_tick` caller, keeping `_advance_relay_phases` sync.

---

**STOP — awaiting review of DP-1…DP-4 before any Phase B implementation.**
