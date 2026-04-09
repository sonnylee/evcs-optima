from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from simulation.base import SimulationModule

if TYPE_CHECKING:
    from simulation.hardware.output import Output


class VehicleState(str, Enum):
    IDLE = "IDLE"
    CHARGING = "CHARGING"
    COMPLETE = "COMPLETE"


class Vehicle(SimulationModule):
    """Electric vehicle — holds SOC curve, updates SOC each dt."""

    def __init__(
        self,
        vehicle_id: str,
        battery_capacity_kwh: float,
        soc_power_curve: list[tuple[float, float]],
        initial_soc: float,
        target_soc: float,
    ):
        self.vehicle_id = vehicle_id
        self.battery_capacity_kwh = battery_capacity_kwh
        # sorted breakpoints: [(soc%, max_power_kw), ...]
        self.soc_power_curve = sorted(soc_power_curve, key=lambda p: p[0])
        self.current_soc = initial_soc
        self.target_soc = target_soc
        self.state = VehicleState.IDLE
        self.max_require_power_kw: float = self._interpolate_power(initial_soc)
        self.present_power_kw: float = 0.0
        self.output: Output | None = None

    def _interpolate_power(self, soc: float) -> float:
        """Linear interpolation on SOC-power curve."""
        soc = max(0.0, min(100.0, soc))
        curve = self.soc_power_curve
        if not curve:
            return 0.0
        if soc <= curve[0][0]:
            return curve[0][1]
        if soc >= curve[-1][0]:
            return curve[-1][1]
        for i in range(len(curve) - 1):
            s0, p0 = curve[i]
            s1, p1 = curve[i + 1]
            if s0 <= soc <= s1:
                t = (soc - s0) / (s1 - s0)
                return p0 + t * (p1 - p0)
        return 0.0

    def step(self, dt: float) -> None:
        if self.output is None or self.state == VehicleState.COMPLETE:
            return

        if self.state == VehicleState.IDLE:
            self.state = VehicleState.CHARGING

        # 1. Update SOC from previous step's power
        if self.present_power_kw > 0:
            delta_energy_kwh = self.present_power_kw * (dt / 3600.0)
            delta_soc = (delta_energy_kwh / self.battery_capacity_kwh) * 100.0
            self.current_soc = min(self.current_soc + delta_soc, 100.0)

        # 2. Check completion
        if self.current_soc >= self.target_soc:
            self.current_soc = min(self.current_soc, self.target_soc)
            self.present_power_kw = 0.0
            self.state = VehicleState.COMPLETE
            self.output.present_power_kw = 0.0
            return

        # 3. Update max require power from curve
        self.max_require_power_kw = self._interpolate_power(self.current_soc)

        # 4. Negotiate present power
        self.present_power_kw = min(self.max_require_power_kw, self.output.available_power_kw)
        self.output.present_power_kw = self.present_power_kw

    def get_status(self) -> dict[str, Any]:
        return {
            "vehicle_id": self.vehicle_id,
            "state": self.state.value,
            "current_soc": round(self.current_soc, 4),
            "target_soc": self.target_soc,
            "max_require_power_kw": round(self.max_require_power_kw, 2),
            "present_power_kw": round(self.present_power_kw, 2),
            "battery_capacity_kwh": self.battery_capacity_kwh,
        }
