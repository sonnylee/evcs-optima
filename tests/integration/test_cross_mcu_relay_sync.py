"""Cross-MCU relay sync integration tests."""

import asyncio
import pytest
from simulation.communication.messages import Stop, Tick
from simulation.hardware.relay import RelayState
from simulation.log.relay_event_log import RelayEventLog
from simulation.modules.mcu_control import (
    GROUPS_PER_MCU,
    OUTPUTS_PER_MCU,
    MCUControl,
)
from tests.conftest import assign_across_station, get_owner_anywhere


# ── Index-agnostic helpers (SPIKE-XMCU-REPORT Phase A, C1 regression) ──────
#
# Every group / output / relay below is DERIVED from GROUPS_PER_MCU /
# OUTPUTS_PER_MCU and the live MCU objects — never a hard-coded group-index or
# relay-name literal — so the tests stay valid if the per-MCU shape changes.


def _group_base(mcu_id: int) -> int:
    return mcu_id * GROUPS_PER_MCU


def _abs_output(mcu_id: int, local_idx: int) -> int:
    return mcu_id * OUTPUTS_PER_MCU + local_idx


def _anchor_groups(mcu_id: int, local_idx: int) -> list[int]:
    """The two min-guarantee groups an output anchors on (SPEC §11).

    O0 → the two leftmost local groups, O1 → the two rightmost — the same
    pairing `output_min_guarantee_kw` uses.
    """
    gb = _group_base(mcu_id)
    return [gb + 2 * local_idx, gb + 2 * local_idx + 1]


def _boundary_groups_toward(lender_id: int, neighbour_id: int, n: int) -> list[int]:
    """The `n` groups of `lender_id` physically closest to `neighbour_id`.

    Linear (non-wrapping) adjacency — adequate because every scenario here
    borrows between immediately adjacent, non-seam MCUs.
    """
    gb = _group_base(lender_id)
    if neighbour_id < lender_id:  # neighbour sits to the lender's left edge
        return list(range(gb, gb + n))
    return list(range(gb + GROUPS_PER_MCU - n, gb + GROUPS_PER_MCU))


def _internal_relay_for(lender: MCUControl, groups: list[int]):
    """The lender-owned inter-group relay bridging `groups` (a contiguous pair
    inside the lender's territory)."""
    local0 = min(g - _group_base(lender._mcu_id) for g in groups)
    return lender._board.inter_group_relays[local0]


def _build_linear_system(num_mcus: int):
    """A `num_mcus`-MCU system with linear neighbour wiring (mirrors the
    conftest `make_3mcu_system` fixture, parameterised on count)."""
    from simulation.hardware.charging_station import ChargingStation

    event_log = RelayEventLog()
    station = ChargingStation(mcu_id=0, event_log=event_log, num_mcus=num_mcus)
    station.initialize(dt_index=0)
    mcus = [
        MCUControl(
            mcu_id=i,
            board=station.boards[i],
            module_assignment=station.boards[i].module_assignment,
            relay_matrix=station.boards[i].relay_matrix,
            event_log=event_log,
            station=station,
            num_mcus=num_mcus,
            consecutive_threshold=1,
        )
        for i in range(num_mcus)
    ]
    for i in range(num_mcus):
        mcus[i].right_neighbor = mcus[i + 1] if i < num_mcus - 1 else None
        mcus[i].left_neighbor = mcus[i - 1] if i > 0 else None
    return station, mcus


def _arrange_xmcu_borrow(station, mcus, borrower_id, borrower_local, lender_id, borrowed):
    """Place `mcus[borrower_id]`'s output in a settled cross-MCU borrow that
    owns `borrowed` (a list of lender groups), then resync the lender's relays.

    Done with the low-level MA + relay API (as the borrow/return tests above
    do) rather than the trigger loop, so the borrow direction is irrelevant.
    """
    abs_out = _abs_output(borrower_id, borrower_local)
    span = _anchor_groups(borrower_id, borrower_local) + list(borrowed)
    lo, hi = min(span), max(span)
    for g in range(lo, hi + 1):
        assign_across_station(station, abs_out, g)
    state = mcus[borrower_id]._output_states[borrower_local]
    state.interval_min = lo
    state.interval_max = hi
    mcus[borrower_id]._apply_global_relay_state()
    # SPEC §11: the lender switches its OWN relays for groups lent out.
    mcus[lender_id]._sync_foreign_relays(step_index=0)
    return abs_out


async def _depart_and_drain(borrower: MCUControl, borrower_local: int):
    """Run the departing output's `_finalize_departure`, then a tick so the
    queued cross-MCU release notices drain through `_handle_tick` (DP-2)."""
    state = borrower._output_states[borrower_local]
    borrower._finalize_departure(state)
    await borrower._handle_tick(
        Tick(dt=1.0, step_index=borrower._step_index + 1, done=asyncio.Event())
    )


@pytest.mark.asyncio
async def test_borrow_and_return_relay_consistency(make_3mcu_system):
    """After borrow and return, all relays return to their original state."""
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    task1 = asyncio.create_task(mcu1.run())
    try:
        # Record initial bridge state
        bridge = station.bridge_relay_between(0)
        assert bridge is not None
        assert bridge.state == RelayState.OPEN

        # Borrow G4
        state = mcu0._output_states[0]
        state.interval_min = 0
        state.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        await mcu0._try_borrow_async(state)
        assert bridge.state == RelayState.CLOSED

        # Return G4
        await mcu0._try_return_async(state)
        assert bridge.state == RelayState.OPEN
        assert get_owner_anywhere(station, 4) is None
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_xmcu_borrower_departure_reopens_lender_relays():
    """T1 — spike minimal reproduction (SPIKE-XMCU-REPORT Phase A, DP-1).

    A borrower owns two of a lender's boundary groups across a closed bridge.
    On departure, the lender's MA was cleared but its bridge + inter-group
    relays stayed orphaned-CLOSED (the bug). After the fix the lender resyncs
    via the deferred ReturnNotify and reopens them.
    """
    borrower_id, lender_id = 0, 1
    borrower_local = 0
    station, mcus = _build_linear_system(3)
    borrower, lender = mcus[borrower_id], mcus[lender_id]

    borrowed = _boundary_groups_toward(lender_id, borrower_id, n=2)
    abs_out = _arrange_xmcu_borrow(
        station, mcus, borrower_id, borrower_local, lender_id, borrowed
    )
    bridge = lender._board.left_bridge_relay
    internal = _internal_relay_for(lender, borrowed)

    # Initial state — borrow is live (≡ spike step 193).
    assert bridge.state == RelayState.CLOSED
    assert internal.state == RelayState.CLOSED
    for g in borrowed:
        assert station.boards[lender_id].module_assignment.get_owner(g) == abs_out

    lender_task = asyncio.create_task(lender.run())
    try:
        await _depart_and_drain(borrower, borrower_local)

        # Final state — RED before the fix, GREEN after (≡ spike step 196).
        assert bridge.state == RelayState.OPEN
        assert internal.state == RelayState.OPEN
        for g in borrowed:
            assert station.boards[lender_id].module_assignment.get_owner(g) is None
    finally:
        lender.stop()
        await lender.send(Stop())
        lender_task.cancel()
        try:
            await lender_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_xmcu_partial_departure_preserves_other_lender_relays():
    """T2 — one lender lends to both neighbours; only one borrower departs
    (SPIKE-XMCU-REPORT Phase A, DP-3.1).

    Verifies three things at once: (a) the fix notifies the lender so the
    departed side's relay reopens; (b) the lender's resync is needed-based —
    the still-borrowed side stays CLOSED; (c) MA stays consistent under a
    partial cross-MCU release.
    """
    lender_id = 2
    left_id, right_id = lender_id - 1, lender_id + 1
    local = 0
    station, mcus = _build_linear_system(4)
    lender = mcus[lender_id]

    left_groups = _boundary_groups_toward(lender_id, left_id, n=2)
    right_groups = _boundary_groups_toward(lender_id, right_id, n=2)
    left_out = _arrange_xmcu_borrow(station, mcus, left_id, local, lender_id, left_groups)
    right_out = _arrange_xmcu_borrow(station, mcus, right_id, local, lender_id, right_groups)

    left_relay = _internal_relay_for(lender, left_groups)   # lender's left edge
    right_relay = _internal_relay_for(lender, right_groups)  # lender's right edge
    lender_ma = station.boards[lender_id].module_assignment

    # Initial state — both sides borrowed.
    assert left_relay.state == RelayState.CLOSED
    assert right_relay.state == RelayState.CLOSED
    for g in left_groups:
        assert lender_ma.get_owner(g) == left_out
    for g in right_groups:
        assert lender_ma.get_owner(g) == right_out

    lender_task = asyncio.create_task(lender.run())
    try:
        # Only the right borrower departs.
        await _depart_and_drain(mcus[right_id], local)

        # (a) departed side reopened.
        assert right_relay.state == RelayState.OPEN
        # (b) still-borrowed side untouched (needed-based resync).
        assert left_relay.state == RelayState.CLOSED
        # (c) MA consistent under partial release.
        for g in right_groups:
            assert lender_ma.get_owner(g) is None
        for g in left_groups:
            assert lender_ma.get_owner(g) == left_out
    finally:
        lender.stop()
        await lender.send(Stop())
        lender_task.cancel()
        try:
            await lender_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_multiple_borrows_relay_chain(make_3mcu_system):
    """Borrowing multiple groups across MCU boundary closes the right relays."""
    station, mcus = make_3mcu_system()
    mcu0, mcu1, mcu2 = mcus

    task1 = asyncio.create_task(mcu1.run())
    try:
        state = mcu0._output_states[0]
        state.interval_min = 0
        state.interval_max = 3
        for g in range(4):
            assign_across_station(station, 0, g)
        mcu0._apply_global_relay_state()

        # Borrow G4
        await mcu0._try_borrow_async(state)
        assert state.interval_max == 4

        # Borrow G5
        await mcu0._try_borrow_async(state)
        assert state.interval_max == 5
        assert station.boards[1].module_assignment.get_owner(5) == 0

        # MCU1's inter-group relay between G4-G5 should be closed
        mcu1_r01 = mcu1._board.inter_group_relays[0]  # G4-G5
        assert mcu1_r01.state == RelayState.CLOSED
    finally:
        mcu1.stop()
        await mcu1.send(Stop())
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass
