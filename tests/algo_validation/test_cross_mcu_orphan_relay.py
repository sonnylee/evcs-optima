"""Deterministic regression guard — cross-MCU borrower departure orphan relay.

Bug class
---------
A cross-MCU borrower that releases a lender's group on departure must make the
lender re-sync its own relays. Before the fix, `_finalize_departure` only did
`ma.release + _mirror_release` (clearing the MA mirror) and never notified the
lender MCU, so the lender's inter-group / bridge relay was left **orphaned
CLOSED** even though the group it gated was owned by nobody.

How it was found (F1 exploration / A1 invariant)
------------------------------------------------
The A1 relay<->ownership invariant in the exploration harness caught this
*probabilistically*: with seed=12345 the run happened to reach the offending
path around step 847 ("inter-group CLOSED but groups not co-owned"), where A1
fired. A different seed could miss the path entirely and let the bug regress
unnoticed — hence this minimal, deterministic, seed-independent guard.

Production fix
--------------
commit 7ac4599 (C1) — `_finalize_departure` (simulation/modules/mcu_control.py:656)
queues each foreign-group release into `_pending_foreign_release_notifies`,
drained by `_drain_pending_foreign_release_notifies` (mcu_control.py:705) from
`_handle_tick` (mcu_control.py:203); the lender then clears its MA and re-syncs
its relays in `_handle_return_notify` -> `_sync_foreign_relays`. This is the
symmetric counterpart of the live-return path `_try_return_async` (mcu_control.py:319).

Scenario (verified canonical cross-MCU borrow)
----------------------------------------------
One high-demand EV at output 0 (MCU0.O0, anchor g0). Default module powers are
[50, 75, 75, 50] = 250 kW per MCU, so 375 kW = 250 (own MCU) + 50 (g4) + 75 (g5)
forces output 0 to exhaust its own MCU and then borrow exactly the two-group
pair g4,g5 from MCU1 (right neighbour; SPEC §2.2 right>left makes this the
natural first cross-MCU step). Borrowing a *pair* is what closes a lender
*inter-group* relay — MCU1.inter_group_relays[0] (g4-g5) — which is precisely the
relay that was orphaned. On departure that relay (and the bridge) must reopen
and the MA mirror must clear on both sides.

(Note: the original draft of this guard targeted output 6 -> MCU2.R_23 at
200 kW. That does not reproduce: 200/250 kW is satisfiable inside the borrower's
own 250 kW MCU, and MCU3.O0's cross-MCU borrow goes to MCU0 via the ring wrap,
never MCU2. The output-0 -> MCU1 case above is the verified equivalent.)

*** This test must NEVER be silenced or weakened. If it fails, the cross-MCU
departure protocol regressed. ***
"""
from __future__ import annotations

import pytest

from simulation.environment.simulation_engine import SimulationEngine
from simulation.hardware.relay import RelayState
from tests.algo_validation.helpers.arrive_inject import inject_arrive
from tests.algo_validation.helpers.async_driver import ExplorationDriver
from tests.algo_validation.helpers.quiescence import is_quiescent

# Canonical scenario constants (see module docstring for the derivation).
_BORROWER_OUTPUT = 0          # MCU0.O0, anchor g0
_BORROWER_MAX_KW = 375        # forces borrowing the g4,g5 pair from MCU1
_LENDER_MCU = 1               # MCU1 lends g4,g5 to output 0
_LENDER_RELAY_IDX = 0         # MCU1.inter_group_relays[0] bridges g4-g5
_BORROWED_GROUPS = (4, 5)     # the two foreign groups output 0 takes from MCU1
_SETTLE_BUDGET = 80           # ticks to reach quiescence (generous; settles in <10)


async def _drive_to_quiescent(driver: ExplorationDriver) -> bool:
    for _ in range(_SETTLE_BUDGET):
        await driver.tick()
        if is_quiescent(driver.engine):
            return True
    return False


@pytest.mark.asyncio
async def test_cross_mcu_borrower_depart_releases_lender_relay(
    empty_engine: SimulationEngine,
) -> None:
    """Cross-MCU borrow -> borrower departs -> lender relay + MA must release.

    Locks in commit 7ac4599 (C1). See module docstring — DO NOT weaken.
    """
    engine = empty_engine
    lender_board = engine.station.boards[_LENDER_MCU]
    lender_relay = lender_board.inter_group_relays[_LENDER_RELAY_IDX]
    lender_ma = lender_board.module_assignment
    borrower_ma = engine.station.boards[_BORROWER_OUTPUT // 2].module_assignment

    driver = ExplorationDriver(engine)
    await driver.start_actors()
    try:
        # 1 high-demand EV at output 0 forces the cross-MCU borrow of g4,g5.
        inject_arrive(
            engine, _BORROWER_OUTPUT, "low",
            max_kw=_BORROWER_MAX_KW, battery_kwh=5.0,
        )
        assert await _drive_to_quiescent(driver), "borrow did not settle"

        # ── Precondition: the borrow actually crossed the MCU boundary. ──
        assert lender_relay.state == RelayState.CLOSED, (
            "precondition failed: lender inter-group relay never closed — "
            f"demand {_BORROWER_MAX_KW} kW did not force a cross-MCU borrow"
        )
        for g in _BORROWED_GROUPS:
            assert borrower_ma.get_owner(g) == _BORROWER_OUTPUT
            assert lender_ma.get_owner(g) == _BORROWER_OUTPUT, (
                f"precondition failed: lender MCU does not mirror g{g} ownership"
            )
        # MA mirror is consistent across the boundary (reuse production check).
        assert engine.validator._diff_pair(_BORROWER_OUTPUT // 2, _LENDER_MCU) == []

        # ── Force departure: EV meets its requirement -> system departs it. ──
        engine.vehicles[0].current_soc = engine.vehicles[0].target_soc
        assert await _drive_to_quiescent(driver), "departure did not settle"

        # ── KEY ASSERT: the orphaned-closed-relay regression. ──
        assert lender_relay.state == RelayState.OPEN, (
            "Lender (MCU1) inter-group relay left CLOSED after cross-MCU "
            "borrower (output 0) departed — orphaned closed relay regression "
            "(commit 7ac4599 / C1)"
        )
        # MA mirror must be clear on BOTH sides.
        for g in _BORROWED_GROUPS:
            assert lender_ma.get_owner(g) is None, f"lender still owns g{g}"
            assert borrower_ma.get_owner(g) is None, f"borrower still mirrors g{g}"
    finally:
        await driver.stop_actors()
