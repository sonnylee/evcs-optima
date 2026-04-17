"""Tests for ConfigLoader — simulation/utils/config_loader.py (0% → cover)."""
from __future__ import annotations

import json
import os
import pytest

from simulation.utils.config_loader import (
    ConfigLoader,
    SimulationConfig,
    VehicleProfile,
    InitialVehiclePlacement,
)

_CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "associate", "ev_curve_data.csv"
)


class TestSimulationConfig:
    def test_default_values(self):
        cfg = SimulationConfig()
        assert cfg.dt == 1.0
        assert cfg.t_end == 3600.0
        assert cfg.num_mcus == 1
        assert cfg.consecutive_threshold == 3
        assert cfg.vehicle_profiles == []
        assert cfg.initial_vehicles == []

    def test_custom_values(self):
        cfg = SimulationConfig(dt=0.5, t_end=7200.0, num_mcus=4)
        assert cfg.dt == 0.5
        assert cfg.t_end == 7200.0
        assert cfg.num_mcus == 4


class TestVehicleProfile:
    def test_construction(self):
        vp = VehicleProfile("TestEV", 100.0, [(0.0, 250.0), (80.0, 50.0)])
        assert vp.name == "TestEV"
        assert vp.battery_capacity_kwh == 100.0
        assert len(vp.soc_power_curve) == 2


class TestInitialVehiclePlacement:
    def test_construction(self):
        ivp = InitialVehiclePlacement("TestEV", 2, 20.0, 80.0)
        assert ivp.vehicle_profile_name == "TestEV"
        assert ivp.output_index == 2
        assert ivp.initial_soc == 20.0
        assert ivp.target_soc == 80.0


class TestConfigLoaderCSV:
    def test_load_csv_returns_profiles(self):
        profiles = ConfigLoader.load_csv(_CSV_PATH)
        assert len(profiles) > 0

    def test_load_csv_profile_has_required_fields(self):
        profiles = ConfigLoader.load_csv(_CSV_PATH)
        for name, p in profiles.items():
            assert isinstance(p.name, str)
            assert p.battery_capacity_kwh > 0
            assert len(p.soc_power_curve) > 0

    def test_load_csv_curve_sorted_by_soc(self):
        profiles = ConfigLoader.load_csv(_CSV_PATH)
        for p in profiles.values():
            socs = [pt[0] for pt in p.soc_power_curve]
            assert socs == sorted(socs)

    def test_load_default_returns_config(self):
        cfg = ConfigLoader.load_default()
        assert isinstance(cfg, SimulationConfig)
        assert cfg.num_mcus == 1
        assert len(cfg.vehicle_profiles) == 1
        assert len(cfg.initial_vehicles) == 1

    def test_load_default_vehicle_placed_at_output_0(self):
        cfg = ConfigLoader.load_default()
        assert cfg.initial_vehicles[0].output_index == 0


class TestConfigLoaderFile:
    def test_load_file_basic(self, tmp_path):
        data = {
            "dt": 2.0,
            "t_end": 1800.0,
            "num_mcus": 3,
            "consecutive_threshold": 5,
            "vehicle_profiles": [
                {
                    "name": "TestEV",
                    "battery_capacity_kwh": 80.0,
                    "soc_power_curve": [[0.0, 200.0], [80.0, 50.0]],
                }
            ],
            "initial_vehicles": [
                {
                    "vehicle_profile_name": "TestEV",
                    "output_index": 1,
                    "initial_soc": 25.0,
                    "target_soc": 75.0,
                }
            ],
        }
        path = str(tmp_path / "config.json")
        with open(path, "w") as f:
            json.dump(data, f)

        cfg = ConfigLoader.load_file(path)
        assert cfg.dt == 2.0
        assert cfg.t_end == 1800.0
        assert cfg.num_mcus == 3
        assert cfg.consecutive_threshold == 5
        assert len(cfg.vehicle_profiles) == 1
        assert cfg.vehicle_profiles[0].name == "TestEV"
        assert cfg.vehicle_profiles[0].battery_capacity_kwh == 80.0
        assert len(cfg.initial_vehicles) == 1
        assert cfg.initial_vehicles[0].output_index == 1
        assert cfg.initial_vehicles[0].initial_soc == 25.0

    def test_load_file_defaults_when_keys_missing(self, tmp_path):
        data = {"vehicle_profiles": [], "initial_vehicles": []}
        path = str(tmp_path / "config_minimal.json")
        with open(path, "w") as f:
            json.dump(data, f)

        cfg = ConfigLoader.load_file(path)
        assert cfg.dt == 1.0
        assert cfg.t_end == 3600.0
        assert cfg.num_mcus == 1
        assert cfg.consecutive_threshold == 3

    def test_load_file_soc_curve_as_tuples(self, tmp_path):
        data = {
            "vehicle_profiles": [
                {
                    "name": "EV",
                    "battery_capacity_kwh": 60.0,
                    "soc_power_curve": [[0, 100], [50, 80], [100, 0]],
                }
            ],
            "initial_vehicles": [],
        }
        path = str(tmp_path / "config.json")
        with open(path, "w") as f:
            json.dump(data, f)

        cfg = ConfigLoader.load_file(path)
        curve = cfg.vehicle_profiles[0].soc_power_curve
        assert curve[0] == (0, 100)
        assert curve[2] == (100, 0)


class TestConfigLoaderCSVEdgeCases:
    def test_load_csv_skips_short_rows(self, tmp_path):
        """Line 55: rows with fewer than 5 columns are silently skipped."""
        path = str(tmp_path / "short.csv")
        with open(path, "w") as f:
            f.write("header\n")          # header (skipped by next())
            f.write("only,two\n")        # < 5 cols → skip
            f.write("EV,20,100.0,x,75.0\n")  # valid row
        profiles = ConfigLoader.load_csv(path)
        assert len(profiles) == 1

    def test_load_csv_skips_empty_kw(self, tmp_path):
        """Line 55 (kw_str empty): rows with blank power column are skipped."""
        path = str(tmp_path / "empty_kw.csv")
        with open(path, "w") as f:
            f.write("header\n")
            f.write("EV,20,,x,75.0\n")   # kw_str is empty → skip
            f.write("EV,30,150.0,x,75.0\n")
        profiles = ConfigLoader.load_csv(path)
        # Only one valid data point → still one profile
        assert "EV" in profiles
        assert len(profiles["EV"].soc_power_curve) == 1

    def test_load_csv_skips_non_numeric_rows(self, tmp_path):
        """Lines 64-65: ValueError on bad numeric fields → continue (row skipped)."""
        path = str(tmp_path / "bad.csv")
        with open(path, "w") as f:
            f.write("header\n")
            f.write("EV,BADSOC,100.0,x,75.0\n")   # soc not int → ValueError
            f.write("EV,20,BADKW,x,75.0\n")        # kw not float → ValueError
            f.write("EV,20,100.0,x,BADCAP\n")      # capacity not float → ValueError
            f.write("EV,40,200.0,x,75.0\n")        # valid
        profiles = ConfigLoader.load_csv(path)
        assert "EV" in profiles
        assert len(profiles["EV"].soc_power_curve) == 1
