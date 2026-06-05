"""``is_quiescent`` — settled-state detector for the exploration harness.

S1 settled definition (per the v4 spec, §4.4): the system is *quiescent* when

  1. all four per-Output pending indicators are ``0`` across every MCU
     (``pending_intergroup_close`` / ``pending_output_relay_close`` /
     ``pending_intergroup_open`` / ``pending_output_relay_open`` — see
     ``mcu_control.py:76-82``), AND
  2. no ``RelayEventLog`` entry was stamped in the last ``_STABLE_WINDOW``
     completed steps.

Indicator (1) mirrors the web layer's ``WebSessionEngine._all_pending_clear``
(``web_session_engine.py:220-230``) — the only place in the tree that
aggregates all four indicators. The simulation *core* exposes no such query
(``SimulationEngine._all_charging_complete`` looks at the two *open* indicators
only, ``simulation_engine.py:216-220``), so we reproduce the ~6-line aggregation
here in the test layer rather than touch production.

``_STABLE_WINDOW`` ≥ 2 already covers the three-phase close sequence; 5 matches
the web settle loop's convergence window so the two detectors agree.

Constants are defined locally on purpose — see the SoT comment below.
"""
from __future__ import annotations

from typing import Any

# SoT: web_session_engine.py:56-57 (`_CONVERGE_STABLE_WINDOW=5`,
# `_CONVERGE_TIMEOUT_TICKS=200`). The simulation core has no such constants, and
# we deliberately do NOT import web_session_engine: it pulls `app.*` (FastAPI)
# dependencies that the simulation test layer must stay free of.
_STABLE_WINDOW = 5
_TIMEOUT_TICKS = 200


def _all_pending_clear(engine: Any) -> bool:
    """True when every MCU's per-Output pending indicators are all 0.

    Copy of ``WebSessionEngine._all_pending_clear`` — see module docstring for
    why this lives here and not in the engine.
    """
    for mcu in engine.mcu_controls:
        for s in mcu._output_states:
            if (
                s.pending_intergroup_close != 0
                or s.pending_output_relay_close != 0
                or s.pending_intergroup_open != 0
                or s.pending_output_relay_open != 0
            ):
                return False
    return True


def is_quiescent(engine: Any) -> bool:
    """True when the engine has settled (S1).

    Pure read of engine state — no streak bookkeeping needed: the "no new
    events for ``_STABLE_WINDOW`` consecutive steps" condition is derived
    directly from the ``RelayEventLog`` by scanning the most recent
    ``_STABLE_WINDOW`` completed step indices.

    Call *after* ``TimeController.tick()`` for a given step, so the last
    completed step is ``step_index - 1``; the scan covers
    ``[step_index - _STABLE_WINDOW, step_index - 1]`` (negative indices, i.e.
    before the run started, count as event-free).
    """
    if not _all_pending_clear(engine):
        return False
    cur = engine.time_controller.step_index
    for step in range(cur - _STABLE_WINDOW, cur):
        if step < 0:
            continue
        if engine.event_log.get_events_at(step):
            return False
    return True
