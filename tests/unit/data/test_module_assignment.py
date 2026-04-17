"""TC-MA-01 to TC-MA-09: ModuleAssignment tests."""

import pytest
from simulation.data.module_assignment import ModuleAssignment


# TC-MA-01: single MCU — all assignable, no owners
def test_single_mcu_all_assignable():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    for g in range(4):
        assert ma.is_assignable(0, g) is True
        assert ma.is_assignable(1, g) is True
        assert ma.get_owner(g) is None


# TC-MA-02: 3-MCU — non-neighbor groups not assignable
def test_3mcu_reachability():
    ma = ModuleAssignment(num_outputs=6, num_groups=12, num_mcus=3)
    # MCU0 outputs (O0, O1) cannot reach MCU2 groups (G8-G11)
    # ring_distance(0, 2, 3) == 1 so they ARE reachable in a 3-MCU ring
    # Instead, check something truly unreachable — not applicable for 3-MCU ring
    # since all MCUs are within distance 1. Test with 4 MCUs instead.
    ma4 = ModuleAssignment(num_outputs=8, num_groups=16, num_mcus=4)
    # MCU0 (O0,O1) cannot reach MCU2 (distance=2)
    assert ma4.is_assignable(0, 8) is False   # G8 on MCU2
    assert ma4.is_assignable(0, 9) is False
    # MCU0 can reach MCU1 (distance=1)
    assert ma4.is_assignable(0, 4) is True
    # MCU0 can reach MCU3 (distance=1 in ring)
    assert ma4.is_assignable(0, 12) is True


# TC-MA-03: assign_if_idle — success
def test_assign_if_idle_success():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    assert ma.assign_if_idle(0, 0) is True
    assert ma.get_owner(0) == 0


# TC-MA-04: assign_if_idle — already owned by another
def test_assign_if_idle_already_owned():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma.assign_if_idle(0, 0)
    assert ma.assign_if_idle(1, 0) is False


# TC-MA-05: assign_if_idle — unreachable cell
def test_assign_if_idle_unreachable():
    ma = ModuleAssignment(num_outputs=8, num_groups=16, num_mcus=4)
    assert ma.assign_if_idle(0, 8) is False  # MCU0 cannot reach MCU2


# TC-MA-06: release then reassign
def test_release_then_reassign():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.release(0, 0)
    assert ma.get_owner(0) is None
    assert ma.assign_if_idle(1, 0) is True


# TC-MA-07: get_groups_for_output
def test_get_groups_for_output():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    assert ma.get_groups_for_output(0) == [0, 1]
    assert ma.get_groups_for_output(1) == []


# TC-MA-08: is_contiguous — linear
def test_is_contiguous_linear():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 1)
    ma.assign_if_idle(0, 2)
    assert ma.is_contiguous(0) is True

    # Non-contiguous: G0 and G2 (gap at G1)
    ma2 = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma2.assign_if_idle(0, 0)
    ma2.assign_if_idle(0, 2)
    assert ma2.is_contiguous(0) is False


# TC-MA-09: is_contiguous — ring wrap
def test_is_contiguous_ring_wrap():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma.assign_if_idle(0, 0)
    ma.assign_if_idle(0, 3)
    # Ring: G0 and G3 form a contiguous ring wrap
    assert ma.is_contiguous(0, ring=True) is True
    # Linear: not contiguous
    assert ma.is_contiguous(0, ring=False) is False


# TC-NEG-06: assign() when already owned by another → AssertionError
def test_assign_already_owned_raises():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma.assign(0, 0)
    with pytest.raises(AssertionError):
        ma.assign(1, 0)


# Additional: to_dict
def test_to_dict():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    d = ma.to_dict()
    assert d["num_outputs"] == 2
    assert d["num_groups"] == 4
    assert len(d["matrix"]) == 2


# Additional: single group is contiguous
def test_single_group_contiguous():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    ma.assign_if_idle(0, 0)
    assert ma.is_contiguous(0) is True


# Additional: no groups is contiguous
def test_no_groups_contiguous():
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    assert ma.is_contiguous(0) is True
