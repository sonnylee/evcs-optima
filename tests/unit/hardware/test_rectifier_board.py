"""RectifierBoard tests."""

from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.hardware.relay import RelayState
from simulation.log.relay_event_log import RelayEventLog


def test_basic_construction():
    el = RelayEventLog()
    rm = RelayMatrix(num_mcus=1)
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    board = RectifierBoard(mcu_id=0, event_log=el, relay_matrix=rm,
                           module_assignment=ma, num_mcus=1)

    assert len(board.groups) == 4
    assert len(board.inter_group_relays) == 3
    assert len(board.output_relays) == 2
    assert len(board.outputs) == 2
    assert board.right_bridge_relay is None


def test_with_right_bridge():
    el = RelayEventLog()
    rm = RelayMatrix(num_mcus=3)
    ma = ModuleAssignment(num_outputs=6, num_groups=12, num_mcus=3)
    board = RectifierBoard(mcu_id=0, event_log=el, relay_matrix=rm,
                           module_assignment=ma, num_mcus=3, has_right_bridge=True)
    assert board.right_bridge_relay is not None


def test_step_passthrough():
    el = RelayEventLog()
    rm = RelayMatrix(num_mcus=1)
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    board = RectifierBoard(mcu_id=0, event_log=el, relay_matrix=rm,
                           module_assignment=ma, num_mcus=1)
    board.step(1.0)  # should not raise


def test_get_status():
    el = RelayEventLog()
    rm = RelayMatrix(num_mcus=1)
    ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
    board = RectifierBoard(mcu_id=0, event_log=el, relay_matrix=rm,
                           module_assignment=ma, num_mcus=1)
    status = board.get_status()
    assert "mcu_id" in status
    assert len(status["groups"]) == 4
    assert len(status["relays"]) == 5  # 3 inter-group + 2 output
