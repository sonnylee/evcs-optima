"""TC-RM-01 to TC-RM-05: RelayMatrix tests (per-MCU 3-MCU window, SPEC §10)."""

import pytest
from simulation.data.relay_matrix import RelayMatrix


# TC-RM-01: 1-MCU topology — single-MCU window collapses to 6×6.
def test_single_mcu_topology():
    rm = RelayMatrix(mcu_id=0, num_mcus=1)
    # Inter-group: G0-G1, G1-G2, G2-G3 (absolute group indices)
    assert rm.is_legal(0, 1) is True
    assert rm.is_legal(1, 2) is True
    assert rm.is_legal(2, 3) is True
    # Output: O0 (abs 4 in flat namespace = 4*1 + 0) ↔ G0
    # In 1-MCU mode the absolute output namespace starts at num_mcus*4 = 4.
    assert rm.is_legal(4, 0) is True   # O0 ↔ G0
    assert rm.is_legal(5, 3) is True   # O1 ↔ G3
    # Non-connected
    assert rm.is_legal(0, 3) is False
    assert rm.is_legal(4, 1) is False


# TC-RM-02: 3-MCU bridges visible in MCU0's window (left=MCU2, self=MCU0, right=MCU1).
def test_3mcu_bridges_in_window():
    rm = RelayMatrix(mcu_id=0, num_mcus=3)
    # Right bridge: MCU0.G3 ↔ MCU1.G0 (abs 3 ↔ 4)
    assert rm.is_legal(3, 4) is True
    # Ring wrap bridge: MCU2.G3 ↔ MCU0.G0 (abs 11 ↔ 0) — 3-MCU is ring
    assert rm.is_legal(11, 0) is True
    # MCU1↔MCU2 bridge (abs 7 ↔ 8) — visible only from MCU1 or MCU2's window,
    # NOT from MCU0's window (MCU2 is in slot[0] left and MCU1 in slot[2] right;
    # they are not consecutive slots from MCU0's POV → no wire here).
    assert rm.is_legal(7, 8) is False


# TC-RM-02b: same bridge IS visible from the right MCU's perspective.
def test_3mcu_bridges_visible_from_owner():
    rm1 = RelayMatrix(mcu_id=1, num_mcus=3)
    # MCU1's window covers {MCU0, MCU1, MCU2}; bridge MCU1.G3 ↔ MCU2.G0 is here.
    assert rm1.is_legal(7, 8) is True


# TC-RM-03: 4-MCU ring bridge visible from owner's window.
def test_4mcu_ring_bridge():
    rm0 = RelayMatrix(mcu_id=0, num_mcus=4)
    # MCU3.G3 ↔ MCU0.G0 (abs 15 ↔ 0); MCU0's window covers {MCU3, MCU0, MCU1}.
    assert rm0.is_legal(15, 0) is True


# TC-RM-04: set_state / get_state on absolute indices.
def test_set_get_state():
    rm = RelayMatrix(mcu_id=0, num_mcus=1)
    rm.set_state(0, 1, 1)  # close
    assert rm.get_state(0, 1) == 1
    assert rm.get_state(1, 0) == 1  # symmetric

    rm.set_state(0, 1, 0)  # open
    assert rm.get_state(0, 1) == 0


# TC-RM-05: set_state on illegal connection raises AssertionError.
def test_set_state_illegal_raises():
    rm = RelayMatrix(mcu_id=0, num_mcus=1)
    with pytest.raises(AssertionError):
        rm.set_state(0, 3, 1)  # no wire between G0 and G3


# TC-RM-06: out-of-window cells silently rejected (SPEC §10).
def test_out_of_window_rejected():
    # 4-MCU ring: MCU0's window does NOT cover MCU2.
    rm0 = RelayMatrix(mcu_id=0, num_mcus=4)
    # MCU2.G0 = abs 8 — outside MCU0's {MCU3, MCU0, MCU1} window.
    assert rm0.is_legal(8, 9) is False
    assert rm0.get_state(8, 9) == -1
    # set_state on out-of-window is a silent no-op.
    rm0.set_state(8, 9, 1)
    assert rm0.get_state(8, 9) == -1


# TC-RM-07: abs ↔ local translation.
def test_abs_local_translation():
    rm = RelayMatrix(mcu_id=0, num_mcus=4)
    # MCU0 self groups → slot 1 (in [left=MCU3, self=MCU0, right=MCU1]).
    assert rm.abs_to_local_group(0) == 4   # slot 1, offset 0 → local 4
    assert rm.abs_to_local_group(3) == 7
    # Right neighbor MCU1 → slot 2.
    assert rm.abs_to_local_group(4) == 8
    # Left neighbor MCU3 (wrap) → slot 0.
    assert rm.abs_to_local_group(12) == 0
    # Non-neighbor MCU2 → None.
    assert rm.abs_to_local_group(8) is None
    # Reverse:
    assert rm.local_to_abs_group(4) == 0
    assert rm.local_to_abs_group(0) == 12
