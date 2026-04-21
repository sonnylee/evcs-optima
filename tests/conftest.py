import pytest
from simulation.log.relay_event_log import RelayEventLog
from simulation.hardware.rectifier_board import RectifierBoard
from simulation.modules.mcu_control import MCUControl


@pytest.fixture
def event_log():
    return RelayEventLog()


@pytest.fixture
def make_single_mcu_system(event_log):
    """1-MCU minimal system fixture, no ChargingStation.

    Per SPEC §10, the board owns its per-MCU RelayMatrix and
    ModuleAssignment; the fixture surfaces them via attribute access for
    legacy tests that asserted on the matrix directly.
    """
    def _make(consecutive_threshold=1):
        board = RectifierBoard(mcu_id=0, event_log=event_log, num_mcus=1)
        ma = board.module_assignment
        rm = board.relay_matrix
        mcu = MCUControl(
            mcu_id=0, board=board, module_assignment=ma,
            relay_matrix=rm, event_log=event_log,
            num_mcus=1, consecutive_threshold=consecutive_threshold,
        )
        return mcu, board, ma, rm
    return _make


@pytest.fixture
def make_3mcu_system(event_log):
    """3-MCU ring system fixture (standard dev/validation config).

    Each MCU receives ITS OWN board's per-MCU MA + RelayMatrix (SPEC §10).
    """
    def _make(consecutive_threshold=1):
        from simulation.hardware.charging_station import ChargingStation
        station = ChargingStation(mcu_id=0, event_log=event_log, num_mcus=3)
        station.initialize(dt_index=0)
        mcus = []
        for i in range(3):
            mcu = MCUControl(
                mcu_id=i,
                board=station.boards[i],
                module_assignment=station.boards[i].module_assignment,
                relay_matrix=station.boards[i].relay_matrix,
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


def assign_across_station(station, abs_output_idx: int, abs_group_idx: int) -> None:
    """SPEC §10 helper: pre-populate the same (Output, Group) ownership
    on every board's MA whose 3-MCU window covers both indices. Tests use
    this as the per-MCU equivalent of the old shared-MA `assign_if_idle`."""
    for board in station.boards:
        board.module_assignment.assign_if_idle(abs_output_idx, abs_group_idx)


def get_owner_anywhere(station, abs_group_idx: int) -> int | None:
    """Return the absolute Output that owns `abs_group_idx`, scanning each
    board's MA in turn. Useful for assertions that don't care which MCU's
    view is consulted."""
    for board in station.boards:
        owner = board.module_assignment.get_owner(abs_group_idx)
        if owner is not None:
            return owner
    return None
