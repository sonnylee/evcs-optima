from __future__ import annotations

from simulation.modules.vehicle import Vehicle
from simulation.utils.config_loader import VehicleProfile


class VehicleGenerator:
    """Creates Vehicle instances from VehicleProfile records.

    Called by TrafficSimulator when an arrival is scheduled.
    """

    def __init__(self, profiles: dict[str, VehicleProfile]):
        self.profiles = profiles
        self._counter = 0

    def generate(
        self,
        profile_name: str,
        initial_soc: float,
        target_soc: float,
        vehicle_id: str | None = None,
    ) -> Vehicle:
        profile = self.profiles[profile_name]
        if vehicle_id is None:
            self._counter += 1
            vehicle_id = f"EV{self._counter}"
        return Vehicle(
            vehicle_id=vehicle_id,
            battery_capacity_kwh=profile.battery_capacity_kwh,
            soc_power_curve=profile.soc_power_curve,
            initial_soc=initial_soc,
            target_soc=target_soc,
        )
