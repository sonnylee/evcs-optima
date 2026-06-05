"""Thin adapters over the engine's *existing* validation / state-read surface.

The v4 spec (§4.1) mandates maximal reuse: the exploration harness must not
re-implement boundary checks, contiguity / ownership checks, or state readout.
These wrappers just forward to production code so call sites read cleanly and
the reuse is explicit. No validation logic is reimplemented here.

Reused production surface:
  - ``Validator.check(step_idx)``        — per-tick boundary consistency (SPEC §9)
  - ``ChargingStation.validate()``       — L2 contiguity + single-owner
  - ``RelayEventLog`` (via ``events_since``)
  - live ``Output.connected_vehicle``    — occupancy reconstruction (C3)

S2 note (snapshot.violations ≡ validator per-tick output):
  ``SimulationEngine._collect_snapshot`` (``simulation_engine.py:247-253``)
  computes ``violations = self.station.validate()`` and *also* calls
  ``self.validator.check(step_idx)``; ``Validator.check`` itself re-runs
  ``self.station.validate()`` (``validator.py:34``) and appends any result to
  ``violations_log``. So both the per-step ``snapshot["violations"]`` field and
  the validator's ``violations_log`` are produced by the *same*
  ``ChargingStation.validate()`` call semantics at the same step — the snapshot
  field IS the validator's per-tick output, just surfaced one step earlier in
  the same function. ``run_station_validate`` is the canonical source for both.
"""
from __future__ import annotations

from typing import Any


def run_boundary_check(validator: Any, step_idx: int) -> list[dict[str, Any]]:
    """Forward to ``Validator.check`` — per-tick boundary consistency (SPEC §9).

    Returns the boundary-check entries for ``step_idx`` (also accumulated into
    ``validator.boundary_log`` / ``validator.violations_log`` as a side effect,
    exactly as production does).
    """
    return validator.check(step_idx)


def run_station_validate(station: Any) -> list[str]:
    """Forward to ``ChargingStation.validate`` — L2 contiguity + single-owner."""
    return station.validate()


def read_state_from_snapshot(engine: Any) -> tuple[int, str | None]:
    """Reconstruct the occupancy state ``(O, L)`` from live engine state.

    ``O`` (C3): an 8-bit occupancy vector where bit ``i`` is set iff
    ``engine._all_outputs[i].connected_vehicle is not None``. Read back from the
    live outputs rather than parsed out of a snapshot row.

    ``L`` (last-arrival SOC level) is a *lossy, test-tracked* abstraction and
    cannot be reconstructed from engine state alone (the engine keeps each
    vehicle's own SOC, not "the last arrival's bucket"). It is supplied by the
    coverage tracker (Commit 2), so this adapter returns ``None`` for ``L`` —
    the observable half of the state only.
    """
    occupancy = 0
    for i, output in enumerate(engine._all_outputs):
        if output.connected_vehicle is not None:
            occupancy |= 1 << i
    return occupancy, None


def events_since(engine: Any, baseline: int) -> list[Any]:
    """Relay events appended since ``baseline`` (a prior ``len(event_log)``)."""
    return engine.event_log.get_events()[baseline:]
