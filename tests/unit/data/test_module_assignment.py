"""TC-MA-01 to TC-MA-09: ModuleAssignment tests (per-MCU 3-MCU window, SPEC §10)."""

import pytest
from simulation.data.module_assignment import ModuleAssignment


# TC-MA-01: single MCU — all assignable, no owners
def test_single_mcu_all_assignable():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    for g in range(4):
        assert ma.is_assignable(0, g) is True
        assert ma.is_assignable(1, g) is True
        assert ma.get_owner(g) is None


# TC-MA-02: 4-MCU — non-neighbor groups not assignable from outside-window POV.
def test_4mcu_reachability():
    # MCU0's window covers {MCU3, MCU0, MCU1}; MCU2 is invisible.
    ma0 = ModuleAssignment(mcu_id=0, num_mcus=4)
    # MCU0 (O0,O1) → MCU2 groups (abs 8..11): out-of-window → not assignable.
    assert ma0.is_assignable(0, 8) is False
    # MCU0 → MCU1 (right neighbor, distance=1): assignable.
    assert ma0.is_assignable(0, 4) is True
    # MCU0 → MCU3 (left wrap, distance=1 in ring): assignable.
    assert ma0.is_assignable(0, 12) is True


# TC-MA-03: assign_if_idle — success
def test_assign_if_idle_success():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    assert ma.assign_if_idle(0, 0) is True
    assert ma.get_owner(0) == 0


# TC-MA-04: assign_if_idle — already owned by another
def test_assign_if_idle_already_owned():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma.assign_if_idle(0, 0)
    assert ma.assign_if_idle(1, 0) is False


# TC-MA-05: assign_if_idle — out-of-window → False (SPEC §10)
def test_assign_if_idle_out_of_window():
    ma0 = ModuleAssignment(mcu_id=0, num_mcus=4)
    # abs group 8 (MCU2) is outside MCU0's window → silently rejected.
    assert ma0.assign_if_idle(0, 8) is False


# TC-MA-06: release then reassign
def test_release_then_reassign():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.release(0, 0)
    assert ma.get_owner(0) is None
    assert ma.assign_if_idle(1, 0) is True


# TC-MA-07: get_groups_for_output (returns absolute group indices)
def test_get_groups_for_output():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    assert ma.get_groups_for_output(0) == [0, 1]
    assert ma.get_groups_for_output(1) == []


# TC-MA-08: is_contiguous — linear
def test_is_contiguous_linear():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    ma.assign_if_idle(0, 2)
    assert ma.is_contiguous(0) is True

    # Non-contiguous: G0 and G2 (gap at G1)
    ma2 = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma2.assign_if_idle(0, 0)
    ma2.assign_if_idle(0, 2)
    assert ma2.is_contiguous(0) is False


# TC-MA-09: is_contiguous — ring wrap
def test_is_contiguous_ring_wrap():
    # 1-MCU "ring" is degenerate but the contiguity helper still operates
    # on the absolute group indices, so abs 0 + abs 3 wrap on N=4 group ring.
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 3)
    assert ma.is_contiguous(0, ring=True) is True
    assert ma.is_contiguous(0, ring=False) is False


# TC-NEG-06: assign() when already owned by another → AssertionError
def test_assign_already_owned_raises():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma.assign(0, 0)
    with pytest.raises(AssertionError):
        ma.assign(1, 0)


# Additional: to_dict
def test_to_dict():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    d = ma.to_dict()
    assert d["num_outputs"] == 2
    assert d["num_groups"] == 4
    assert len(d["matrix"]) == 2
    assert d["mcu_id"] == 0


# Additional: single group is contiguous
def test_single_group_contiguous():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    ma.assign_if_idle(0, 0)
    assert ma.is_contiguous(0) is True


# Additional: no groups is contiguous
def test_no_groups_contiguous():
    ma = ModuleAssignment(mcu_id=0, num_mcus=1)
    assert ma.is_contiguous(0) is True


# SPEC §10 ownership: an owner update on one MCU's MA does NOT propagate
# automatically to a different MCU's MA — they are independent instances.
def test_per_mcu_isolation():
    ma0 = ModuleAssignment(mcu_id=0, num_mcus=4)
    ma1 = ModuleAssignment(mcu_id=1, num_mcus=4)
    # MCU0's MA window covers {MCU3, MCU0, MCU1}; MCU1's covers {MCU0, MCU1, MCU2}.
    # abs G4 (MCU1.G0) is in BOTH windows.
    assert ma0.assign_if_idle(0, 4) is True
    # ma1's mirror is independent; needs its own write to reflect the borrow.
    assert ma1.get_owner(4) is None
    ma1.assign_if_idle(0, 4)
    assert ma1.get_owner(4) == 0
