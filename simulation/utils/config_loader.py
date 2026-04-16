import csv
import json
import os
from dataclasses import dataclass, field


@dataclass
class VehicleProfile:
    name: str
    battery_capacity_kwh: float
    soc_power_curve: list[tuple[float, float]]  # [(soc%, max_power_kw), ...]


@dataclass
class InitialVehiclePlacement:
    vehicle_profile_name: str
    output_index: int  # index into the station's outputs list
    initial_soc: float
    target_soc: float


@dataclass
class SimulationConfig:
    dt: float = 1.0              # seconds per time step
    t_end: float = 3600.0        # total simulation time (seconds)
    num_mcus: int = 1
    vehicle_profiles: list[VehicleProfile] = field(default_factory=list)
    initial_vehicles: list[InitialVehiclePlacement] = field(default_factory=list)
    # SPEC §6.1/§6.2: borrow/return only fires after the trigger condition
    # has held for N consecutive steps. Tunable per run.
    consecutive_threshold: int = 3


_CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "associate", "ev_curve_data.csv"
)
DEFAULT_VEHICLE_NAME = "2024 Tesla Cybertruck Cyberbeast (325 kW, optimized)"

# Default EV charging curve (typical CCS profile) — fallback reference
DEFAULT_SOC_POWER_CURVE: list[tuple[float, float]] = [
    (0.0, 50.0),
    (10.0, 100.0),
    (20.0, 125.0),
    (50.0, 125.0),
    (80.0, 100.0),
    (90.0, 50.0),
    (100.0, 0.0),
]


class ConfigLoader:

    @staticmethod
    def load_csv(csv_path: str | None = None) -> dict[str, VehicleProfile]:
        """Parse EV charging curves from CSV into VehicleProfile objects."""
        if csv_path is None:
            csv_path = _CSV_PATH

        raw_data: dict[str, dict] = {}

        with open(csv_path, newline="") as f:
            reader = csv.reader(f)
            next(reader)  # skip header
            for row in reader:
                if len(row) < 5:
                    continue
                name = row[0].strip()
                kw_str = row[2].strip()
                if not kw_str:
                    continue
                try:
                    soc = int(row[1].strip())
                    kw = float(kw_str)
                    capacity = float(row[4].strip())
                except ValueError:
                    continue

                if name not in raw_data:
                    raw_data[name] = {"capacity": capacity, "soc_powers": {}}
                soc_powers = raw_data[name]["soc_powers"]
                if soc not in soc_powers:
                    soc_powers[soc] = []
                soc_powers[soc].append(kw)

        profiles: dict[str, VehicleProfile] = {}
        for name, data in raw_data.items():
            curve = sorted(
                (float(soc), sum(powers) / len(powers))
                for soc, powers in data["soc_powers"].items()
            )
            profiles[name] = VehicleProfile(
                name=name,
                battery_capacity_kwh=data["capacity"],
                soc_power_curve=curve,
            )
        return profiles

    @staticmethod
    def load_default() -> SimulationConfig:
        profiles = ConfigLoader.load_csv()
        cybertruck = profiles[DEFAULT_VEHICLE_NAME]
        return SimulationConfig(
            dt=1.0,
            t_end=3600.0,
            num_mcus=1,
            vehicle_profiles=[cybertruck],
            initial_vehicles=[
                InitialVehiclePlacement(cybertruck.name, 0, 20.0, 80.0),
            ],
        )

    @staticmethod
    def load_file(path: str) -> SimulationConfig:
        with open(path) as f:
            data = json.load(f)

        profiles = [
            VehicleProfile(
                name=p["name"],
                battery_capacity_kwh=p["battery_capacity_kwh"],
                soc_power_curve=[tuple(pt) for pt in p["soc_power_curve"]],
            )
            for p in data.get("vehicle_profiles", [])
        ]

        vehicles = [
            InitialVehiclePlacement(
                vehicle_profile_name=v["vehicle_profile_name"],
                output_index=v["output_index"],
                initial_soc=v["initial_soc"],
                target_soc=v["target_soc"],
            )
            for v in data.get("initial_vehicles", [])
        ]

        return SimulationConfig(
            dt=data.get("dt", 1.0),
            t_end=data.get("t_end", 3600.0),
            num_mcus=data.get("num_mcus", 1),
            consecutive_threshold=data.get("consecutive_threshold", 3),
            vehicle_profiles=profiles,
            initial_vehicles=vehicles,
        )
