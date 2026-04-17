"""TC-VEH-01 to TC-VEH-05: Vehicle tests."""

from unittest.mock import MagicMock

from simulation.modules.vehicle import Vehicle, VehicleState


def _make_vehicle(curve=None, initial_soc=20.0, target_soc=80.0, battery_kwh=75.0):
    if curve is None:
        curve = [(0, 250), (80, 250), (100, 0)]
    return Vehicle("V1", battery_kwh, curve, initial_soc, target_soc)


# TC-VEH-01: _interpolate_power — curve endpoints
def test_interpolate_power_endpoints():
    curve = [(0, 250), (80, 250), (100, 0)]
    v = _make_vehicle(curve=curve)
    v.current_soc = 0
    assert v._interpolate_power(0) == 250.0
    assert v._interpolate_power(100) == 0.0


# TC-VEH-02: _interpolate_power — linear interpolation
def test_interpolate_power_linear():
    curve = [(0, 0), (100, 200)]
    v = _make_vehicle(curve=curve)
    result = v._interpolate_power(50)
    assert abs(result - 100.0) < 0.01


# TC-VEH-03: step() updates SOC
def test_step_updates_soc():
    v = _make_vehicle(initial_soc=20.0, target_soc=80.0, battery_kwh=75.0)
    v.state = VehicleState.CHARGING
    v.present_power_kw = 100.0
    # Mock output so step() doesn't bail
    mock_output = MagicMock()
    mock_output.available_power_kw = 200.0
    mock_output.present_power_kw = 0.0
    v.output = mock_output

    old_soc = v.current_soc
    v.step(dt=60.0)  # 1 minute
    # delta = (100 * 60/3600) / 75 * 100 ≈ 2.22%
    assert v.current_soc > old_soc
    assert v.state == VehicleState.CHARGING


# TC-VEH-04: step() reaching target_soc → COMPLETE
def test_step_reaches_target():
    v = _make_vehicle(initial_soc=79.9, target_soc=80.0, battery_kwh=75.0)
    v.state = VehicleState.CHARGING
    v.present_power_kw = 250.0
    mock_output = MagicMock()
    mock_output.available_power_kw = 250.0
    mock_output.present_power_kw = 0.0
    v.output = mock_output

    v.step(dt=3600.0)  # 1 hour — more than enough to reach 80%
    assert v.state == VehicleState.COMPLETE
    assert v.present_power_kw == 0.0


# TC-VEH-05: step() with output=None → no-op
def test_step_no_output_noop():
    v = _make_vehicle()
    v.output = None
    old_soc = v.current_soc
    old_state = v.state
    v.step(1.0)
    assert v.current_soc == old_soc
    assert v.state == old_state


# Additional: empty curve returns 0
def test_interpolate_power_empty_curve():
    v = _make_vehicle(curve=[])
    assert v._interpolate_power(50.0) == 0.0


# Additional: below first curve point
def test_interpolate_power_below_first():
    v = _make_vehicle(curve=[(10, 200), (100, 0)])
    assert v._interpolate_power(5.0) == 200.0


# Additional: step() with IDLE state transitions to CHARGING
def test_step_idle_to_charging():
    v = _make_vehicle(initial_soc=20.0)
    mock_output = MagicMock()
    mock_output.available_power_kw = 125.0
    mock_output.present_power_kw = 0.0
    v.output = mock_output
    assert v.state == VehicleState.IDLE
    v.step(60.0)
    assert v.state == VehicleState.CHARGING


# Additional: step() with COMPLETE is no-op
def test_step_complete_noop():
    v = _make_vehicle()
    v.state = VehicleState.COMPLETE
    mock_output = MagicMock()
    v.output = mock_output
    old_soc = v.current_soc
    v.step(60.0)
    assert v.current_soc == old_soc


# Additional: get_status
def test_get_status():
    v = _make_vehicle()
    s = v.get_status()
    assert s["vehicle_id"] == "V1"
    assert s["state"] == "IDLE"
    assert "current_soc" in s
    assert "max_require_power_kw" in s
