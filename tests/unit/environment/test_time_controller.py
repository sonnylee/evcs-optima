"""Tests for TimeController — simulation/environment/time_controller.py (0% → 100%)."""
import pytest
from simulation.environment.time_controller import TimeController


class TestTimeController:
    def test_initial_state(self):
        tc = TimeController(dt=1.0, t_end=10.0)
        assert tc.current_time == 0.0
        assert tc.step_index == 0
        assert tc.dt == 1.0
        assert tc.t_end == 10.0

    def test_is_finished_false_initially(self):
        tc = TimeController(dt=1.0, t_end=10.0)
        assert not tc.is_finished()

    def test_tick_advances_time_and_step(self):
        tc = TimeController(dt=1.0, t_end=10.0)
        result = tc.tick()
        assert result == pytest.approx(1.0)
        assert tc.current_time == pytest.approx(1.0)
        assert tc.step_index == 1

    def test_tick_multiple_times(self):
        tc = TimeController(dt=0.5, t_end=10.0)
        for _ in range(6):
            tc.tick()
        assert tc.current_time == pytest.approx(3.0)
        assert tc.step_index == 6

    def test_is_finished_at_t_end(self):
        tc = TimeController(dt=1.0, t_end=3.0)
        tc.tick(); tc.tick(); tc.tick()
        assert tc.is_finished()

    def test_is_finished_just_before_t_end(self):
        tc = TimeController(dt=1.0, t_end=3.0)
        tc.tick(); tc.tick()
        assert not tc.is_finished()

    def test_step_calls_tick(self):
        tc = TimeController(dt=1.0, t_end=10.0)
        tc.step(dt=1.0)
        assert tc.step_index == 1
        assert tc.current_time == pytest.approx(1.0)

    def test_get_status(self):
        tc = TimeController(dt=2.0, t_end=100.0)
        tc.tick()
        s = tc.get_status()
        assert s["current_time"] == pytest.approx(2.0)
        assert s["step_index"] == 1
        assert s["dt"] == 2.0
        assert s["t_end"] == 100.0

    def test_get_status_rounds_time(self):
        """current_time is rounded to 6 decimal places in get_status."""
        tc = TimeController(dt=0.1, t_end=10.0)
        for _ in range(3):
            tc.tick()
        s = tc.get_status()
        assert s["current_time"] == pytest.approx(0.3, abs=1e-5)


# ── vision_output missing lines 127, 184 ─────────────────────────────────────
# (placed here to avoid new file overhead; logically separate)

import csv as _csv
import json as _json
import os as _os
from simulation.environment.vision_output import VisionOutput


def _vo_snapshot(vo, relay_state=None, relay_events=None, arrivals=None, vehicles=None):
    num_mcus = vo.num_mcus
    relay_state = relay_state or {}
    for m in range(num_mcus):
        p = f"MCU{m}"
        for k in [f"{p}_R_O0", f"{p}_R_O1", f"{p}_R01", f"{p}_R12", f"{p}_R23"]:
            relay_state.setdefault(k, "OFF")
        relay_state.setdefault(f"{p}_BR", "OFF")
    vbo = vehicles or {}
    for m in range(num_mcus):
        for o in range(2):
            vbo.setdefault(f"MCU{m}_O{o}", None)
    station_status = {"boards": [
        {"relays": [{"relay_id": k, "state": "CLOSED" if v == "ON" else "OPEN"}
                    for k, v in relay_state.items() if k.startswith(f"MCU{m}")]}
        for m in range(num_mcus)
    ]}
    vo.record_snapshot(
        step_index=1, current_time=1.0,
        station_status=station_status,
        vehicles_by_output=vbo,
        new_relay_events=relay_events or [],
        arrivals=arrivals or [],
    )


class TestVisionOutput:
    # ── Label building ────────────────────────────────────────────────────────
    def test_output_relay_labels(self):
        vo = VisionOutput(num_mcus=1)
        assert vo._relay_labels["MCU0_R_O0"] == "M1.O1"
        assert vo._relay_labels["MCU0_R_O1"] == "M1.O2"

    def test_inter_group_labels(self):
        vo = VisionOutput(num_mcus=1)
        assert vo._relay_labels["MCU0_R01"] == "M1.R2"
        assert vo._relay_labels["MCU0_R12"] == "M1.R3"
        assert vo._relay_labels["MCU0_R23"] == "M1.R4"

    def test_bridge_label_ring_wrap(self):
        # 3-MCU ring: MCU2_BR → M1.R1
        vo = VisionOutput(num_mcus=3)
        assert vo._relay_labels["MCU2_BR"] == "M1.R1"

    # ── Headers ───────────────────────────────────────────────────────────────
    def test_header_count_1mcu(self):
        vo = VisionOutput(num_mcus=1)
        h = vo._build_headers()
        assert len(h) == 5 + 12    # 5 fixed + 2(O)+4(R)+6(EV×2×3)

    def test_header_fixed_cols(self):
        vo = VisionOutput(num_mcus=1)
        assert vo._build_headers()[:5] == [
            "Step", "Time", "Event", "Outputs Ops", "Relays Ops"
        ]

    # ── record_snapshot ───────────────────────────────────────────────────────
    def test_relay_op_goes_to_relay_ops(self):
        vo = VisionOutput(num_mcus=1)
        events = [{"relay_id": "MCU0_R01", "to_state": "CLOSED", "from_state": "OPEN"}]
        _vo_snapshot(vo, relay_events=events)
        assert "R2 closed" in vo._rows[0]["relay_ops"]

    def test_output_relay_event_goes_to_output_ops(self):
        vo = VisionOutput(num_mcus=1)
        events = [{"relay_id": "MCU0_R_O0", "to_state": "CLOSED", "from_state": "OPEN"}]
        _vo_snapshot(vo, relay_events=events)
        assert "O1 closed" in vo._rows[0]["output_ops"]

    def test_arrival_in_event_text(self):
        vo = VisionOutput(num_mcus=1)
        _vo_snapshot(vo, arrivals=[{"vehicle_id": "EV1", "output_id": "MCU0_O0"}])
        assert "EV1 arrived" in vo._rows[0]["event"]

    def test_no_events_yields_dashes(self):
        vo = VisionOutput(num_mcus=1)
        _vo_snapshot(vo)
        assert vo._rows[0]["event"] == "-"
        assert vo._rows[0]["relay_ops"] == "-"
        assert vo._rows[0]["output_ops"] == "-"

    def test_vehicle_power_recorded(self):
        vo = VisionOutput(num_mcus=1)
        veh = {"available_power_kw": 125.0, "max_require_power_kw": 200.0, "current_soc": 35.0}
        _vo_snapshot(vo, vehicles={"MCU0_O0": veh, "MCU0_O1": None})
        assert vo._rows[0]["vehicles_by_output"]["MCU0_O0"]["available_power_kw"] == 125.0

    # ── write_csv ─────────────────────────────────────────────────────────────
    def test_csv_written_success(self, tmp_path):
        vo = VisionOutput(num_mcus=1)
        _vo_snapshot(vo)
        path = str(tmp_path / "trace.csv")
        assert vo.write_csv(path)
        assert _os.path.exists(path)

    def test_csv_blocked_on_failure(self, tmp_path):
        vo = VisionOutput(num_mcus=1)
        path = str(tmp_path / "fail.csv")
        assert not vo.write_csv(path, validator_failed=True)
        assert not _os.path.exists(path)

    def test_csv_row_structure(self, tmp_path):
        vo = VisionOutput(num_mcus=1)
        _vo_snapshot(vo)
        path = str(tmp_path / "trace.csv")
        vo.write_csv(path)
        with open(path) as f:
            rows = list(_csv.reader(f))
        # row[0]=header, row[1]=init, row[2]=data
        assert rows[0][0] == "Step"
        assert rows[1][0] == "Init"
        assert rows[2][0] == "1"

    def test_csv_scenario_name_prepended(self, tmp_path):
        """Line 127: scenario_name row is written before headers."""
        vo = VisionOutput(num_mcus=1, scenario_name="MyScenario")
        _vo_snapshot(vo)
        path = str(tmp_path / "trace.csv")
        vo.write_csv(path)
        with open(path) as f:
            rows = list(_csv.reader(f))
        assert rows[0][0] == "MyScenario"
        assert rows[1][0] == "Step"

    def test_csv_relay_on_off(self, tmp_path):
        vo = VisionOutput(num_mcus=1)
        rs = {"MCU0_R01": "ON"}
        _vo_snapshot(vo, relay_state=rs)
        path = str(tmp_path / "trace.csv")
        vo.write_csv(path)
        with open(path) as f:
            rows = list(_csv.reader(f))
        headers = rows[0]
        r2_idx = headers.index("M1.R2")
        assert rows[2][r2_idx] == "ON"

    def test_csv_m1_r1_hardcoded_off_bug(self, tmp_path):
        """Line 184: m==0 branch hardcodes OFF — documents the known ring bug."""
        vo = VisionOutput(num_mcus=3)
        rs = {"MCU2_BR": "ON"}  # ring bridge should appear as M1.R1
        _vo_snapshot(vo, relay_state=rs)
        path = str(tmp_path / "trace.csv")
        vo.write_csv(path)
        with open(path) as f:
            rows = list(_csv.reader(f))
        headers = rows[0]
        r1_idx = headers.index("M1.R1")
        # Bug: currently hardcoded OFF; expected ON after fix
        assert rows[2][r1_idx] == "OFF"   # documents current (buggy) behaviour

    # ── write_boundary_log ────────────────────────────────────────────────────
    def test_boundary_log_written(self, tmp_path):
        vo = VisionOutput(num_mcus=2)
        entries = [{"type": "boundary_check", "time_step": 0,
                    "mcu_pair": [0, 1], "result": "consistent"}]
        path = str(tmp_path / "boundary.jsonl")
        vo.write_boundary_log(path, entries)
        assert _os.path.exists(path)
        with open(path) as f:
            assert _json.loads(f.read())["result"] == "consistent"

    def test_boundary_log_empty(self, tmp_path):
        vo = VisionOutput(num_mcus=1)
        path = str(tmp_path / "empty.jsonl")
        vo.write_boundary_log(path, [])
        with open(path) as f:
            assert f.read() == ""
