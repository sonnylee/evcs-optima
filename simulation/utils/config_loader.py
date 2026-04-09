import json
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


# Default EV charging curve (typical CCS profile)
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
    def load_default() -> SimulationConfig:
        profile = VehicleProfile(
            name="standard_ev",
            battery_capacity_kwh=60.0,
            soc_power_curve=DEFAULT_SOC_POWER_CURVE,
        )
        return SimulationConfig(
            dt=1.0,
            t_end=3600.0,
            num_mcus=1,
            vehicle_profiles=[profile],
            initial_vehicles=[
                InitialVehiclePlacement("standard_ev", 0, 20.0, 80.0),
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
            vehicle_profiles=profiles,
            initial_vehicles=vehicles,
        )
