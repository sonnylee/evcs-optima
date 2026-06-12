"""Deterministic regression — bridge re-close race on cross-MCU departure.

Bug class (Phase B teardown race; docs/algo_validation/SPIKE_A1_BRIDGE_SEED1.md)
------------------------------------------------------------------------------
Distinct from the C1 *never-opened* orphan (``test_cross_mcu_orphan_relay.py`` /
commit 7ac4599). A cross-MCU borrower whose interval crosses an MCU boundary
closes the boundary **bridge**. On departure the borrower's own MCU correctly
OPENs that bridge (``_open_departure_intergroup_relays``) — but the borrower's
interval and MA ownership are not cleared until ``_finalize_departure`` one
phase-tick later. If the **lender** MCU re-syncs its relays inside that window
(driven by any of its own borrow / return / arrival activity — seed 1 hit it via
the lender's own return), the lender's foreign-span recompute still sees the
departing borrower owning the boundary group and **re-CLOSEs** the bridge. It is
never reopened, leaving it CLOSED over an unowned boundary — caught by A1 at the
next steady point (seed 1, ε=0.0, step 3099).

Production fix
--------------
``_foreign_virtual_span`` (simulation/modules/mcu_control.py) returns ``None``
for a foreign owner that is mid-departure (``pending_intergroup_open`` /
``pending_output_relay_open`` set), so a lender re-sync in the teardown window no
longer counts the borrower's stale interval and cannot re-close the bridge.
Symmetric to the existing local-interval guard in ``_apply_global_relay_state``.

How it was found
----------------
F1 exploration / A1 invariant, seed 1 — a *different* seed than the C1 orphan
(12345), so a seed-bound run would miss it. Hence this minimal, deterministic,
seed-independent guard. Index-agnostic: the boundary group and bridge are
derived from topology (``GROUPS_PER_MCU`` / ``bridge_relay_between``), never
hard-coded.

*** This test must NEVER be silenced or weakened. If it fails, the cross-MCU
departure bridge re-close race regressed. ***
"""
from __future__ import annotations

import pytest

from simulation.environment.simulation_engine import SimulationEngine
from simulation.hardware.relay import RelayState
from simulation.modules.mcu_control import GROUPS_PER_MCU, OUTPUTS_PER_MCU
from tests.algo_validation.helpers.arrive_inject import inject_arrive
from tests.algo_validation.helpers.async_driver import ExplorationDriver
from tests.algo_validation.helpers.quiescence import is_quiescent

# Canonical cross-MCU borrow (reused from test_cross_mcu_orphan_relay): output 0
# (MCU0.O0, anchor at MCU0's first group) at 375 kW exhausts its own 250 kW MCU
# and borrows the first two groups of the *next* MCU — crossing the bridge
# between MCU0 and MCU1, which therefore closes.
_BORROWER_OUTPUT = 0
_BORROWER_MAX_KW = 375
_LENDER_MCU = 1                       # the MCU that lends across the boundary
_BRIDGE_LEFT_MCU = 0                  # bridge(_BRIDGE_LEFT_MCU, _LENDER_MCU)
_SETTLE_BUDGET = 80


def _lender_boundary_group() -> int:
    """Group on the lender side that the bridge gates: the lender MCU's first
    group (topology-derived, never hard-coded)."""
    return _LENDER_MCU * GROUPS_PER_MCU


async def _drive_to_quiescent(driver: ExplorationDriver) -> bool:
    for _ in range(_SETTLE_BUDGET):
        await driver.tick()
        if is_quiescent(driver.engine):
            return True
    return False


@pytest.mark.asyncio
async def test_lender_resync_in_departure_window_keeps_bridge_open(
    empty_engine: SimulationEngine,
) -> None:
    """Cross-MCU borrow closes the bridge -> borrower departs -> a lender re-sync
    fired inside the teardown window must NOT re-close the bridge.

    RED before the `_foreign_virtual_span` departure guard, GREEN after. See the
    module docstring — DO NOT weaken.
    """
    engine = empty_engine
    bridge = engine.station.bridge_relay_between(_BRIDGE_LEFT_MCU)
    assert bridge is not None, "expected a bridge between the first two MCUs"
    lender_ma = engine.station.boards[_LENDER_MCU].module_assignment
    borrower_mcu_id = _BORROWER_OUTPUT // OUTPUTS_PER_MCU
    borrower_ma = engine.station.boards[borrower_mcu_id].module_assignment
    g_bound = _lender_boundary_group()
    borrower_state = engine.mcu_controls[borrower_mcu_id]._output_states[
        _BORROWER_OUTPUT % OUTPUTS_PER_MCU
    ]

    driver = ExplorationDriver(engine)
    await driver.start_actors()
    try:
        # ── Borrow across the boundary; the bridge must close. ──
        inject_arrive(
            engine, _BORROWER_OUTPUT, "low",
            max_kw=_BORROWER_MAX_KW, battery_kwh=5.0,
        )
        assert await _drive_to_quiescent(driver), "borrow did not settle"
        assert bridge.state == RelayState.CLOSED, (
            "precondition failed: demand did not force a cross-MCU borrow over "
            "the bridge"
        )
        assert lender_ma.get_owner(g_bound) == _BORROWER_OUTPUT, (
            "precondition failed: lender does not mirror the borrowed boundary "
            "group"
        )

        # ── Force departure (EV meets requirement -> system departs it). ──
        engine.vehicles[0].current_soc = engine.vehicles[0].target_soc

        # ── Tick into the teardown window: the borrower's MCU has opened the
        #    bridge, but its interval / MA ownership are not yet cleared. ──
        in_window = False
        for _ in range(_SETTLE_BUDGET):
            await driver.tick()
            mid_departure = (
                borrower_state.pending_intergroup_open != 0
                or borrower_state.pending_output_relay_open != 0
            )
            if (
                bridge.state == RelayState.OPEN
                and mid_departure
                and lender_ma.get_owner(g_bound) == _BORROWER_OUTPUT
            ):
                in_window = True
                break
            if is_quiescent(engine):
                break
        assert in_window, (
            "did not reach the departure teardown window (bridge open while the "
            "borrower still owns the boundary group) — scenario drifted"
        )

        # ── Inject a lender re-sync inside the window. This is the exact
        #    production entry a concurrent neighbour borrow/return triggers
        #    (`_handle_borrow_request` / `_handle_return_notify` ->
        #    `_sync_foreign_relays`). ──
        engine.mcu_controls[_LENDER_MCU]._sync_foreign_relays(
            engine.time_controller.step_index
        )

        # ── KEY ASSERT: the lender must NOT re-close the bridge the departure
        #    opened (the Phase B teardown race). ──
        assert bridge.state == RelayState.OPEN, (
            "Lender re-synced inside the departure window and re-CLOSED the "
            "bridge the borrower just opened — Phase B teardown race regression "
            "(SPIKE_A1_BRIDGE_SEED1.md; _foreign_virtual_span departure guard)"
        )

        # ── Settle: bridge stays OPEN and MA clears on both sides. ──
        assert await _drive_to_quiescent(driver), "departure did not settle"
        assert bridge.state == RelayState.OPEN, (
            "bridge re-closed after the departure settled (orphaned closed bridge)"
        )
        assert lender_ma.get_owner(g_bound) is None, "lender still owns boundary group"
        assert borrower_ma.get_owner(g_bound) is None, "borrower still mirrors boundary group"
    finally:
        await driver.stop_actors()
