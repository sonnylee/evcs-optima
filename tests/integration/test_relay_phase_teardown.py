"""Relay-phase teardown race regression (C1.5b).

Directly reproduces the step-1113 teardown race surfaced by the F1 / A1 gate
after C1: ``_open_departure_intergroup_relays`` opens a departing output's
inter-group relays, but the output's ``interval`` is not cleared until
``_finalize_departure`` one phase-tick later. Any ``_apply_global_relay_state``
call in that window (triggered by the sibling output's borrow/return, a foreign
sync, etc.) re-reads the stale interval and RE-CLOSES the relays the departure
just opened — leaving them orphaned-CLOSED once the MA is finally cleared.

This test exercises the mechanism locally and deterministically (single MCU, no
A1 proxy): open → concurrent resync → the relays must stay OPEN. It fails
without the C1.5b guard in ``_apply_global_relay_state`` and passes with it.
"""

from simulation.hardware.relay import RelayState
from simulation.modules.mcu_control import OUTPUTS_PER_MCU


def _abs_output(mcu_id: int, local_idx: int) -> int:
    return mcu_id * OUTPUTS_PER_MCU + local_idx


def test_apply_global_relay_state_skips_departing_outputs(make_single_mcu_system):
    mcu, board, ma, _rm = make_single_mcu_system()
    out_local = 0
    abs_o = _abs_output(mcu_id=0, local_idx=out_local)
    state = mcu._output_states[out_local]

    # The output owns a contiguous interval wide enough to require inter-group
    # relays (anchor + one extension on each side).
    groups = list(range(3))
    for g in groups:
        ma.assign_if_idle(abs_o, g)
    state.interval_min = min(groups)
    state.interval_max = max(groups)
    mcu._apply_global_relay_state()

    # Relays bridging the owned interval (one per consecutive group pair).
    relays = [board.inter_group_relays[i] for i in range(min(groups), max(groups))]
    assert relays, "interval too narrow to exercise inter-group relays"
    assert all(r.state == RelayState.CLOSED for r in relays)

    # Departure phase: open the inter-group relays, then sit in the
    # output-relay-open phase with the interval STILL set (this is exactly the
    # state ``_advance_relay_phases`` leaves between the two phase-ticks).
    mcu._open_departure_intergroup_relays(state)
    assert all(r.state == RelayState.OPEN for r in relays)
    state.pending_output_relay_open = 1

    # A concurrent resync fires in the same window (the step-1113 trigger).
    mcu._apply_global_relay_state()

    # The mid-departure output must NOT re-assert the relays it is tearing down.
    assert all(r.state == RelayState.OPEN for r in relays), (
        "mid-departure output re-closed its own inter-group relays during a "
        "concurrent _apply_global_relay_state (teardown race)"
    )
