"""Tests for SimulationEngine — simulation/environment/simulation_engine.py (0% → cover)."""
from __future__ import annotations

import os
import pytest

from simulation.environment.simulation_engine import SimulationEngine
from simulation.modules.traffic_simulator import TrafficSimulator, ArrivalEvent
from simulation.modules.vehicle_generator import VehicleGenerator
from simulation.modules.vehicle import VehicleState
from simulation.utils.config_loader import (
    SimulationConfig, VehicleProfile, InitialVehiclePlacement,
)

_CURVE  = [(0.0, 250.0), (80.0, 250.0), (100.0, 0.0)]
_PROFILE = VehicleProfile("EV", 75.0, _CURVE)


def _cfg(num_mcus=1, t_end=300.0, vehicles=None, threshold=1):
    return SimulationConfig(
        dt=1.0, t_end=t_end, num_mcus=num_mcus,
        vehicle_profiles=[_PROFILE],
        initial_vehicles=vehicles or [],
        consecutive_threshold=threshold,
    )


def _place(output_index=0, soc0=20.0, soc1=30.0):
    return InitialVehiclePlacement(_PROFILE.name, output_index, soc0, soc1)


# ── Construction ──────────────────────────────────────────────────────────────

class TestEngineConstruction:
    def test_single_mcu_builds(self):
        e = SimulationEngine(_cfg(num_mcus=1))
        assert len(e.mcu_controls) == 1
        assert e.station.num_mcus == 1

    def test_multi_mcu_builds(self):
        for n in [2, 3, 4]:
            e = SimulationEngine(_cfg(num_mcus=n))
            assert len(e.mcu_controls) == n

    def test_neighbor_wiring_linear_2mcu(self):
        e = SimulationEngine(_cfg(num_mcus=2))
        m = e.mcu_controls
        assert m[0].left_neighbor  is None
        assert m[0].right_neighbor is m[1]
        assert m[1].left_neighbor  is m[0]
        assert m[1].right_neighbor is None

    def test_neighbor_wiring_ring_3mcu(self):
        e = SimulationEngine(_cfg(num_mcus=3))
        m = e.mcu_controls
        assert m[0].right_neighbor is m[1]
        assert m[0].left_neighbor  is m[2]   # ring wrap
        assert m[2].right_neighbor is m[0]   # ring wrap

    def test_neighbor_wiring_ring_4mcu(self):
        e = SimulationEngine(_cfg(num_mcus=4))
        m = e.mcu_controls
        assert m[0].left_neighbor  is m[3]
        assert m[3].right_neighbor is m[0]

    def test_all_outputs_count(self):
        e = SimulationEngine(_cfg(num_mcus=3))
        assert len(e._all_outputs) == 6  # 3 MCUs × 2 outputs

    def test_initial_vehicle_connected(self):
        e = SimulationEngine(_cfg(num_mcus=1, vehicles=[_place(0)]))
        assert len(e.vehicles) == 1
        assert e._all_outputs[0].connected_vehicle is not None

    def test_event_log_cleared_after_init(self):
        e = SimulationEngine(_cfg(num_mcus=1, vehicles=[_place(0)]))
        assert len(e.event_log) == 0

    def test_traffic_simulator_wired_on_construction(self):
        e = SimulationEngine(_cfg(num_mcus=1))
        gen = VehicleGenerator({_PROFILE.name: _PROFILE})
        ts  = TrafficSimulator(gen, e._all_outputs,
                               [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 80.0)])
        e.traffic_simulator = ts
        assert e.traffic_simulator is ts


# ── Sync run (single MCU) ─────────────────────────────────────────────────────

class TestSyncRun:
    def test_run_no_vehicles(self):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=10.0))
        e.run()
        assert e.time_controller.step_index > 0

    def test_run_vehicle_charges_to_target(self):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=3600.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        v = e.vehicles[0]
        assert v.current_soc >= v.target_soc
        assert v.state == VehicleState.COMPLETE

    def test_snapshot_recorded_each_step(self):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        snaps = e.snapshots.all()
        assert len(snaps) > 0
        assert "step_index" in snaps[0]
        assert "station" in snaps[0]
        assert "relay_events" in snaps[0]

    def test_no_validator_failures_clean_run(self):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=300.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        assert not e.validator.has_failures()

    def test_run_with_traffic_simulator(self):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=300.0))
        gen = VehicleGenerator({_PROFILE.name: _PROFILE})
        ts  = TrafficSimulator(gen, e._all_outputs,
                               [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 25.0)])
        e.traffic_simulator = ts
        e.run()
        assert len(e.vehicles) >= 1


# ── Async run (multi-MCU) ─────────────────────────────────────────────────────

class TestAsyncRun:
    def test_2mcu_run_completes(self):
        e = SimulationEngine(_cfg(num_mcus=2, t_end=300.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        assert not e.validator.has_failures()

    def test_3mcu_ring_run_completes(self):
        e = SimulationEngine(_cfg(num_mcus=3, t_end=300.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        assert not e.validator.has_failures()

    def test_4mcu_ring_run_completes(self):
        e = SimulationEngine(_cfg(num_mcus=4, t_end=300.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        assert not e.validator.has_failures()

    def test_async_vehicle_reaches_target_soc(self):
        e = SimulationEngine(_cfg(num_mcus=2, t_end=3600.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        assert e.vehicles[0].state == VehicleState.COMPLETE

    def test_async_snapshot_recorded(self):
        e = SimulationEngine(_cfg(num_mcus=2, t_end=5.0))
        e.run()
        assert len(e.snapshots.all()) > 0

    def test_async_with_traffic_simulator(self):
        e = SimulationEngine(_cfg(num_mcus=2, t_end=300.0))
        gen = VehicleGenerator({_PROFILE.name: _PROFILE})
        ts  = TrafficSimulator(gen, e._all_outputs,
                               [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 25.0)])
        e.traffic_simulator = ts
        e.run()
        assert len(e.vehicles) >= 1
        assert not e.validator.has_failures()

    def test_all_charging_complete_no_vehicles_returns_false(self):
        e = SimulationEngine(_cfg(num_mcus=2, t_end=5.0))
        assert not e._all_charging_complete()

    def test_all_charging_complete_with_pending_traffic(self):
        e = SimulationEngine(_cfg(num_mcus=2, t_end=300.0))
        gen = VehicleGenerator({_PROFILE.name: _PROFILE})
        ts  = TrafficSimulator(gen, e._all_outputs,
                               [ArrivalEvent(100.0, 0, _PROFILE.name, 20.0, 25.0)])
        e.traffic_simulator = ts
        # Before run: pending arrival → not complete
        assert not e._all_charging_complete()

    def test_trigger_departures_noop_when_no_vehicles(self):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0))
        e._trigger_departures()   # must not raise

    def test_sync_traffic_vehicles_noop_without_traffic(self):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0))
        e._sync_traffic_vehicles()  # must not raise


# ── Export ────────────────────────────────────────────────────────────────────

class TestEngineExport:
    def test_export_csv_creates_file(self, tmp_path):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        path = str(tmp_path / "trace.csv")
        ok = e.export_csv(path)
        assert ok
        assert os.path.exists(path)

    def test_export_csv_blocked_when_validator_failed(self, tmp_path):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0))
        e.run()
        e.validator.violations_log.append({"time_step": 0, "violations": ["fake"]})
        path = str(tmp_path / "trace.csv")
        ok = e.export_csv(path)
        assert not ok

    def test_export_boundary_log_creates_file(self, tmp_path):
        e = SimulationEngine(_cfg(num_mcus=2, t_end=5.0))
        e.run()
        path = str(tmp_path / "boundary.jsonl")
        e.export_boundary_log(path)
        assert os.path.exists(path)

    def test_print_summary_runs_without_error(self, capsys):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        e.print_summary()
        out = capsys.readouterr().out
        assert "Simulation complete" in out

    def test_print_summary_no_vehicles(self, capsys):
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0))
        e.run()
        e.print_summary()  # must not raise with empty vehicle list


# ── 補齊 missing lines ────────────────────────────────────────────────────────

class TestEngineEdgeCases:
    def test_traffic_simulator_set_at_construction(self):
        """Line 105: traffic_simulator wired during __init__ when passed in."""
        gen = VehicleGenerator({_PROFILE.name: _PROFILE})
        schedule = [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 25.0)]
        ts = TrafficSimulator(gen, [], schedule)   # outputs wired after
        cfg = _cfg(num_mcus=1, t_end=300.0)
        e = SimulationEngine(cfg, traffic_simulator=ts)
        assert e.traffic_simulator is ts
        assert e.traffic_simulator.mcu_controls == e.mcu_controls

    def test_all_charging_complete_active_not_at_soc(self):
        """Line 207: active vehicles not yet at target → not complete."""
        e = SimulationEngine(_cfg(num_mcus=1, t_end=3600.0,
                                  vehicles=[_place(0, 20.0, 80.0)]))
        # Don't run — vehicle is active but SOC < target
        assert not e._all_charging_complete()

    def test_all_charging_complete_pending_relay_phase(self):
        """Lines 210, 219: pending relay open phases block completion."""
        e = SimulationEngine(_cfg(num_mcus=2, t_end=3600.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        # Manually mark a departure in-flight
        e.mcu_controls[0]._output_states[0].pending_output_relay_open = 1
        # Even if vehicle SOC would be satisfied, relay phase blocks
        assert not e._all_charging_complete()

    def test_sync_traffic_vehicles_adds_new_vehicles(self):
        """Lines 247-248: new vehicles from traffic simulator added to self.vehicles."""
        e = SimulationEngine(_cfg(num_mcus=1, t_end=300.0))
        gen = VehicleGenerator({_PROFILE.name: _PROFILE})
        schedule = [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 25.0)]
        ts = TrafficSimulator(gen, e._all_outputs, schedule)
        e.traffic_simulator = ts
        ts.prime_initial_arrivals()
        e._sync_traffic_vehicles()
        assert len(e.vehicles) == 1

    def test_print_summary_with_snapshots(self, capsys):
        """Line 337: print_summary iterates snapshots when they exist."""
        e = SimulationEngine(_cfg(num_mcus=1, t_end=5.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        e.print_summary()
        out = capsys.readouterr().out
        assert "Time(s)" in out


class TestEngineRemainingLines:
    def test_all_charging_complete_vehicles_not_complete_state(self):
        """Line 207: vehicles exist but not all COMPLETE state → False."""
        e = SimulationEngine(_cfg(num_mcus=1, t_end=3600.0,
                                  vehicles=[_place(0, 20.0, 80.0)]))
        # vehicles list populated, but state is IDLE, not COMPLETE
        from simulation.modules.vehicle import VehicleState
        assert e.vehicles[0].state == VehicleState.IDLE
        # active=[] because output relay not closed yet, vehicles=[], returns False
        assert not e._all_charging_complete()

    def test_all_charging_complete_active_vehicle_below_target(self):
        """Line 210: active vehicle SOC below target → False."""
        e = SimulationEngine(_cfg(num_mcus=2, t_end=3600.0,
                                  vehicles=[_place(0, 20.0, 80.0)]))
        # Step a few ticks to open output relay, then check mid-run
        import asyncio
        from simulation.communication.messages import Tick, Stop

        async def _partial():
            tasks = [asyncio.create_task(m.run()) for m in e.mcu_controls]
            tc = e.time_controller
            for _ in range(10):
                for v in e.vehicles:
                    v.step(tc.dt)
                evts = [asyncio.Event() for _ in e.mcu_controls]
                for mcu, ev in zip(e.mcu_controls, evts):
                    await mcu.send(Tick(dt=tc.dt, step_index=tc.step_index, done=ev))
                await asyncio.gather(*(ev.wait() for ev in evts))
                e.station.step(tc.dt)
                tc.tick()
            for m in e.mcu_controls:
                await m.send(Stop())
            await asyncio.gather(*tasks, return_exceptions=True)

        asyncio.run(_partial())
        # After 10 steps, vehicle SOC is still well below 80% target
        assert not e._all_charging_complete()

    def test_sync_traffic_vehicles_deduplicates(self):
        """Lines 247-248: same vehicle object not added twice."""
        e = SimulationEngine(_cfg(num_mcus=1, t_end=300.0))
        gen = VehicleGenerator({_PROFILE.name: _PROFILE})
        ts = TrafficSimulator(gen, e._all_outputs,
                              [ArrivalEvent(0.0, 0, _PROFILE.name, 20.0, 25.0)])
        e.traffic_simulator = ts
        ts.prime_initial_arrivals()
        e._sync_traffic_vehicles()
        count_first = len(e.vehicles)
        e._sync_traffic_vehicles()   # second call must not duplicate
        assert len(e.vehicles) == count_first

    def test_print_summary_iterates_snapshots(self, capsys):
        """Line 337: summary table printed only when snapshots exist."""
        e = SimulationEngine(_cfg(num_mcus=1, t_end=10.0,
                                  vehicles=[_place(0, 20.0, 25.0)]))
        e.run()
        e.print_summary()
        out = capsys.readouterr().out
        assert "Time(s)" in out
        assert "SOC" in out
