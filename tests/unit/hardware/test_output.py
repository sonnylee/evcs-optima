"""TC-OUT-01 to TC-OUT-02: Output tests."""

from unittest.mock import MagicMock

from simulation.hardware.output import Output
from simulation.hardware.smr_group import SMRGroup
from tests.conftest import make_vehicle


def _make_output(**kwargs):
    g0 = SMRGroup("G0", num_smrs=2)  # 50kW
    g1 = SMRGroup("G1", num_smrs=3)  # 75kW
    defaults = dict(
        output_id="O0",
        anchor_group=g0,
        groups=[g0, g1],
    )
    defaults.update(kwargs)
    return defaults.pop("groups"), Output(**defaults) if "groups" not in kwargs else Output(**{**defaults, "groups": [g0, g1]})


# TC-OUT-01: connect_vehicle / disconnect_vehicle
def test_connect_disconnect_vehicle():
    g0 = SMRGroup("G0", num_smrs=2)
    g1 = SMRGroup("G1", num_smrs=3)
    output = Output(output_id="O0", anchor_group=g0, groups=[g0, g1])
    vehicle = make_vehicle()

    output.connect_vehicle(vehicle)
    assert output.connected_vehicle is vehicle
    assert vehicle.output is output

    output.disconnect_vehicle()
    assert output.connected_vehicle is None
    assert vehicle.output is None
    assert output.present_power_kw == 0.0


# TC-OUT-02: connect_vehicle calls module_assignment.assign_if_idle
def test_connect_calls_assign_if_idle():
    g0 = SMRGroup("G0", num_smrs=2)
    g1 = SMRGroup("G1", num_smrs=3)
    ma = MagicMock()
    ma.assign_if_idle = MagicMock(return_value=True)

    output = Output(
        output_id="O0",
        anchor_group=g0,
        groups=[g0, g1],
        module_assignment=ma,
        output_idx=0,
        group_indices=[0, 1],
    )
    vehicle = make_vehicle()
    output.connect_vehicle(vehicle)

    assert ma.assign_if_idle.call_count == 2
    calls = [c.args for c in ma.assign_if_idle.call_args_list]
    assert (0, 0) in calls
    assert (0, 1) in calls
