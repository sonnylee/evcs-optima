"""Tests for TrafficSimulator and VehicleGenerator (0% → 100%)."""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from simulation.modules.traffic_simulator import TrafficSimulator, ArrivalEvent
from simulation.modules.vehicle_generator import VehicleGenerator
from simulation.utils.config_loader import VehicleProfile
from simulation.log.relay_event_log import RelayEventLog
from simulation.data.module_assignment import ModuleAssignment
from simulation.data.relay_matrix import RelayMatrix
from simulation.hardware.rectifier_board import RectifierBoard

_CURVE = [(0.0, 250.0), (80.0, 250.0), (100.0, 0.0)]
_PROFILE = VehicleProfile("EV", 75.0, _CURVE)


def _make_outputs(n_mcus=1):
    log = RelayEventLog()
    rm = RelayMatrix(num_mcus=n_mcus)
    ma = ModuleAssignment(num_outputs=2 * n_mcus, num_groups=4 * n_mcus, num_mcus=n_mcus)
    boards = [
        RectifierBoard(mcu_id=i, event_log=log, relay_matrix=rm,
                       module_assignment=ma, num_mcus=n_mcus)
        for i in range(n_mcus)
    ]
    return [o for b in boards for o in b.outputs]


def _make_gen():
    return VehicleGenerator({_PROFILE.name: _PROFILE})


# ── VehicleGenerator ──────────────────────────────────────────────────────────

class TestVehicleGenerator:
    def test_generate_basic(self):
        gen = _make_gen()
        v = gen.generate(_PROFILE.name, initial_soc=20.0, target_soc=80.0)
        assert v.vehicle_id == "EV1"
        assert v.current_soc == 20.0
        assert v.target_soc == 80.0
        assert v.battery_capacity_kwh == 75.0

    def test_counter_auto_increments(self):
        gen = _make_gen()
        v1 = gen.generate(_PROFILE.name, 20.0, 80.0)
        v2 = gen.generate(_PROFILE.name, 30.0, 90.0)
        assert v1.vehicle_id == "EV1"
        assert v2.vehicle_id == "EV2"

    def test_custom_vehicle_id_skips_counter(self):
        gen = _make_gen()
        v = gen.generate(_PROFILE.name, 20.0, 80.0, vehicle_id="CUSTOM-1")
        assert v.vehicle_id == "CUSTOM-1"
        # Counter not incremented — next auto-id is still EV1
        v2 = gen.generate(_PROFILE.name, 20.0, 80.0)
        assert v2.vehicle_id == "EV1"

    def test_soc_power_curve_transferred(self):
        gen = _make_gen()
        v = gen.generate(_PROFILE.name, 20.0, 80.0)
        assert len(v.soc_power_curve) == len(_CURVE)

    def test_unknown_profile_raises_key_error(self):
        gen = _make_gen()
        with pytest.raises(KeyError):
            gen.generate("NoSuchProfile", 20.0, 80.0)


# ── TrafficSimulator ──────────────────────────────────────────────────────────

class TestTrafficSimulatorStep:
    def test_vehicle_spawned_at_scheduled_time(self):
        outputs = _make_outputs()
        ts = TrafficSimulator(_make_gen(), outputs,
                              [ArrivalEvent(2.0, 0, _PROFILE.name, 20.0, 80.0)])
        ts.step(dt=1.0)
        assert outputs[0].connected_vehicle is None  # t=1.0, not yet
        ts.step(dt=1.0)
        assert outputs[0].connected_vehicle is not None  # t=2.0, spawned

    def test_schedule_sorted_ascending(self):
        outputs = _make_outputs()
        schedule = [
            ArrivalEvent(5.0, 0, _PROFILE.name, 20.0, 80.0),
            ArrivalEvent(1.0, 1, _PROFILE.name, 20.0, 80.0),
        ]
        ts = TrafficSimulator(_make_gen(), outputs, schedule)
        ts.step(dt=1.0)  # t=1.0
        assert outputs[1].connected_vehicle is not None
        assert outputs[0].connected_vehicle is None

    def test_busy_output_drops_arrival(self):
        outputs = _make_outputs()
        schedule = [
            ArrivalEvent(1.0, 0, _PROFILE.name, 20.0, 80.0),
            ArrivalEvent(1.0, 0, _PROFILE.name, 30.0, 90.0),
        ]
        ts = TrafficSimulator(_make_gen(), outputs, schedule)
        ts.step(dt=1.0)
        assert len(ts.vehicles) == 1  # second dropped (output busy)

    def test_multiple_arrivals_same_tick(self):
        outputs = _make_outputs()
        schedule = [
            ArrivalEvent(1.0, 0, _PROFILE.name, 20.0, 80.0),
            ArrivalEvent(1.0, 1, _PROFILE.name, 20.0, 80.0),
        ]
        ts = TrafficSimulator(_make_gen(), outputs, schedule)
        ts.step(dt=1.0)
        assert len(ts.vehicles) == 2

    def test_pending_decrements_after_spawn(self):
        outputs = _make_outputs()
        schedule = [
            ArrivalEvent(1.0, 0, _PROFILE.name, 20.0, 80.0),
            ArrivalEvent(3.0, 1, _PROFILE.name, 20.0, 80.0),
        ]
        ts = TrafficSimulator(_make_gen(), outputs, schedule)
        assert len(ts._pending) == 2
        ts.step(dt=1.0)
        assert len(ts._pending) == 1
        ts.step(dt=1.0); ts.step(dt=1.0)
        assert len(ts._pending) == 0

    def test_arrivals_log_updated(self):
        outputs = _make_outputs()
        ts = TrafficSimulator(_make_gen(), outputs,
                              [ArrivalEvent(1.0, 0, _PROFILE.name, 20.0, 80.0)])
        ts.step(dt=1.0)
        assert len(ts.arrivals_log) == 1
        entry = ts.arrivals_log[0]
        assert entry["output_index"] == 0
        assert "vehicle_id" in entry
        assert "output_id" in entry

    def test_get_status(self):
        outputs = _make_outputs()
        ts = TrafficSimulator(_make_gen(), outputs, [])
        s = ts.get_status()
        assert s["current_time"] == 0.0
        assert s["pending_arrivals"] == 0
        assert s["active_vehicles"] == 0
        assert s["arrivals_log"] == []


class TestTrafficSimulatorPrime:
    def test_prime_spawns_t0_arrivals(self):
        outputs = _make_outputs()
        ts = TrafficSimulator(_make_gen(), outputs,
                              [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 80.0)])
        ts.prime_initial_arrivals()
        assert outputs[0].connected_vehicle is not None

    def test_prime_leaves_future_arrivals_pending(self):
        outputs = _make_outputs()
        schedule = [
            ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 80.0),
            ArrivalEvent(5.0, 1, _PROFILE.name, 20.0, 80.0),
        ]
        ts = TrafficSimulator(_make_gen(), outputs, schedule)
        ts.prime_initial_arrivals()
        assert outputs[0].connected_vehicle is not None
        assert outputs[1].connected_vehicle is None
        assert len(ts._pending) == 1

    def test_prime_with_no_t0_arrivals_is_noop(self):
        outputs = _make_outputs()
        ts = TrafficSimulator(_make_gen(), outputs,
                              [ArrivalEvent(1.0, 0, _PROFILE.name, 20.0, 80.0)])
        ts.prime_initial_arrivals()
        assert outputs[0].connected_vehicle is None
        assert len(ts._pending) == 1


class TestTrafficSimulatorMCUControl:
    def test_mcu_handle_arrival_called_on_spawn(self):
        outputs = _make_outputs()
        ts = TrafficSimulator(_make_gen(), outputs,
                              [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 80.0)])
        mock_mcu = MagicMock()
        ts.mcu_controls = [mock_mcu]
        ts.prime_initial_arrivals()
        mock_mcu.handle_vehicle_arrival.assert_called_once_with(0)

    def test_mcu_handle_arrival_output_index_mapping(self):
        """output_index=3 → mcu_idx=1, local_idx=1."""
        outputs = _make_outputs(n_mcus=2)
        ts = TrafficSimulator(_make_gen(), outputs,
                              [ArrivalEvent(0.0, 3, _PROFILE.name, 20.0, 80.0)])
        mock_mcu0 = MagicMock()
        mock_mcu1 = MagicMock()
        ts.mcu_controls = [mock_mcu0, mock_mcu1]
        ts.prime_initial_arrivals()
        mock_mcu1.handle_vehicle_arrival.assert_called_once_with(1)
        mock_mcu0.handle_vehicle_arrival.assert_not_called()

    def test_no_mcu_controls_does_not_raise(self):
        """Spawning without mcu_controls set must not raise."""
        outputs = _make_outputs()
        ts = TrafficSimulator(_make_gen(), outputs,
                              [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 80.0)])
        ts.prime_initial_arrivals()  # mcu_controls is [] — no error
        assert len(ts.vehicles) == 1
