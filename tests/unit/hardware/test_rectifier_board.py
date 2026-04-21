"""RectifierBoard tests — per-MCU SPEC §10 ownership."""

from simulation.hardware.rectifier_board import RectifierBoard
from simulation.log.relay_event_log import RelayEventLog


def test_basic_construction():
    el = RelayEventLog()
    board = RectifierBoard(mcu_id=0, event_log=el, num_mcus=1)

    assert len(board.groups) == 4
    assert len(board.inter_group_relays) == 3
    assert len(board.output_relays) == 2
    assert len(board.outputs) == 2
    assert board.right_bridge_relay is None
    # Per-MCU instances are owned by the board.
    assert board.relay_matrix.mcu_id == 0
    assert board.module_assignment.mcu_id == 0


def test_with_right_bridge():
    el = RelayEventLog()
    board = RectifierBoard(mcu_id=0, event_log=el, num_mcus=3, has_right_bridge=True)
    assert board.right_bridge_relay is not None


def test_step_passthrough():
    el = RelayEventLog()
    board = RectifierBoard(mcu_id=0, event_log=el, num_mcus=1)
    board.step(1.0)  # should not raise


def test_get_status():
    el = RelayEventLog()
    board = RectifierBoard(mcu_id=0, event_log=el, num_mcus=1)
    status = board.get_status()
    assert "mcu_id" in status
    assert len(status["groups"]) == 4
    assert len(status["relays"]) == 5  # 3 inter-group + 2 output


def test_per_mcu_isolation():
    """Two boards in the same station hold INDEPENDENT data structures."""
    el = RelayEventLog()
    b0 = RectifierBoard(mcu_id=0, event_log=el, num_mcus=4, has_right_bridge=True)
    b1 = RectifierBoard(mcu_id=1, event_log=el, num_mcus=4, has_right_bridge=True)
    assert b0.module_assignment is not b1.module_assignment
    assert b0.relay_matrix is not b1.relay_matrix
