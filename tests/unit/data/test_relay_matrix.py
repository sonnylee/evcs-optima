"""TC-RM-01 to TC-RM-05: RelayMatrix tests."""

import pytest
from simulation.data.relay_matrix import RelayMatrix


# TC-RM-01: 1-MCU topology
def test_single_mcu_topology():
    rm = RelayMatrix(num_mcus=1)
    # Inter-group: G0-G1, G1-G2, G2-G3
    assert rm.is_legal(0, 1) is True
    assert rm.is_legal(1, 2) is True
    assert rm.is_legal(2, 3) is True
    # Output: O0(idx=4)↔G0(idx=0), O1(idx=5)↔G3(idx=3)
    assert rm.is_legal(4, 0) is True
    assert rm.is_legal(5, 3) is True
    # Non-connected
    assert rm.is_legal(0, 3) is False
    assert rm.is_legal(4, 1) is False


# TC-RM-02: 3-MCU bridge relays (ring)
def test_3mcu_bridges():
    rm = RelayMatrix(num_mcus=3)
    # Bridge: MCU0.G3 ↔ MCU1.G0 (idx 3 ↔ 4)
    assert rm.is_legal(3, 4) is True
    # Bridge: MCU1.G3 ↔ MCU2.G0 (idx 7 ↔ 8)
    assert rm.is_legal(7, 8) is True
    # Ring bridge: MCU2.G3 ↔ MCU0.G0 (idx 11 ↔ 0) — 3 MCU is ring
    assert rm.is_legal(11, 0) is True


# TC-RM-03: 4-MCU ring bridge exists
def test_4mcu_ring_bridge():
    rm = RelayMatrix(num_mcus=4)
    # MCU3.G3(idx=15) ↔ MCU0.G0(idx=0)
    assert rm.is_legal(15, 0) is True


# TC-RM-04: set_state / get_state
def test_set_get_state():
    rm = RelayMatrix(num_mcus=1)
    rm.set_state(0, 1, 1)  # close
    assert rm.get_state(0, 1) == 1
    assert rm.get_state(1, 0) == 1  # symmetric

    rm.set_state(0, 1, 0)  # open
    assert rm.get_state(0, 1) == 0


# TC-RM-05: set_state on illegal connection raises AssertionError
def test_set_state_illegal_raises():
    rm = RelayMatrix(num_mcus=1)
    with pytest.raises(AssertionError):
        rm.set_state(0, 3, 1)  # no wire between G0 and G3
