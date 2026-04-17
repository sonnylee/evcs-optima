import pytest
from simulation.log.relay_event_log import RelayEventLog
from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.modules.mcu_control import MCUControl


@pytest.fixture
def event_log():
    return RelayEventLog()


@pytest.fixture
def make_single_mcu_system(event_log):
    """1-MCU minimal system fixture, no ChargingStation."""
    def _make(consecutive_threshold=1):
        rm = RelayMatrix(num_mcus=1)
        ma = ModuleAssignment(num_outputs=2, num_groups=4, num_mcus=1)
        board = RectifierBoard(
            mcu_id=0, event_log=event_log,
            relay_matrix=rm, module_assignment=ma, num_mcus=1,
        )
        mcu = MCUControl(
            mcu_id=0, board=board, module_assignment=ma,
            relay_matrix=rm, event_log=event_log,
            num_mcus=1, consecutive_threshold=consecutive_threshold,
        )
        return mcu, board, ma, rm
    return _make


@pytest.fixture
def make_3mcu_system(event_log):
    """3-MCU linear system fixture (standard dev/validation config)."""
    def _make(consecutive_threshold=1):
        from simulation.hardware.charging_station import ChargingStation
        station = ChargingStation(mcu_id=0, event_log=event_log, num_mcus=3)
        station.initialize(dt_index=0)
        mcus = []
        for i in range(3):
            mcu = MCUControl(
                mcu_id=i,
                board=station.boards[i],
                module_assignment=station.module_assignment,
                relay_matrix=station.relay_matrix,
                event_log=event_log,
                station=station,
                num_mcus=3,
                consecutive_threshold=consecutive_threshold,
            )
            mcus.append(mcu)
        # Wire neighbors linearly (not full ring)
        for i in range(3):
            mcus[i].right_neighbor = mcus[(i + 1) % 3] if i < 2 else None
            mcus[i].left_neighbor = mcus[(i - 1) % 3] if i > 0 else None
        return station, mcus
    return _make


def make_vehicle(
    vehicle_id="V1",
    battery_kwh=75.0,
    initial_soc=20.0,
    target_soc=80.0,
    max_power_kw=250.0,
):
    from simulation.modules.vehicle import Vehicle
    curve = [(0.0, max_power_kw), (80.0, max_power_kw), (100.0, 0.0)]
    return Vehicle(vehicle_id, battery_kwh, curve, initial_soc, target_soc)
