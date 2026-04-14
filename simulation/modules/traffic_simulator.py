from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from simulation.base import SimulationModule
from simulation.modules.vehicle_generator import VehicleGenerator

if TYPE_CHECKING:
    from simulation.hardware.output import Output
    from simulation.modules.mcu_control import MCUControl
    from simulation.modules.vehicle import Vehicle


@dataclass
class ArrivalEvent:
    arrival_time: float
    output_index: int
    vehicle_profile_name: str
    initial_soc: float
    target_soc: float
    vehicle_id: str | None = None


class TrafficSimulator(SimulationModule):
    """Schedules vehicle arrivals and routes them to Outputs.

    Drives a pre-built schedule of ArrivalEvents. At each step, vehicles whose
    `arrival_time` has elapsed are instantiated via VehicleGenerator and
    connected to their target Output. Used by the 14-scenario validation
    runner (SPEC §16) — all arrivals scheduled at t=0 to saturate the matrix.
    """

    def __init__(
        self,
        generator: VehicleGenerator,
        outputs: list[Output],
        schedule: list[ArrivalEvent],
    ):
        self.generator = generator
        self.outputs = outputs
        self._pending: list[ArrivalEvent] = sorted(schedule, key=lambda a: a.arrival_time)
        self._current_time: float = 0.0
        self.vehicles: list[Vehicle] = []
        self.arrivals_log: list[dict[str, Any]] = []
        self.mcu_controls: list[MCUControl] = []

    def step(self, dt: float) -> None:
        self._current_time += dt
        while self._pending and self._pending[0].arrival_time <= self._current_time:
            ev = self._pending.pop(0)
            self._spawn(ev)

    def prime_initial_arrivals(self) -> None:
        """Dispatch all arrivals scheduled at t<=0 immediately (before step 0)."""
        while self._pending and self._pending[0].arrival_time <= 0.0:
            ev = self._pending.pop(0)
            self._spawn(ev)

    def _spawn(self, ev: ArrivalEvent) -> None:
        output = self.outputs[ev.output_index]
        if output.connected_vehicle is not None:
            return  # output busy — drop arrival
        vehicle = self.generator.generate(
            profile_name=ev.vehicle_profile_name,
            initial_soc=ev.initial_soc,
            target_soc=ev.target_soc,
            vehicle_id=ev.vehicle_id,
        )
        output.connect_vehicle(vehicle)
        if self.mcu_controls:
            mcu_idx = ev.output_index // 2
            local_idx = ev.output_index % 2
            self.mcu_controls[mcu_idx].handle_vehicle_arrival(local_idx)
        self.vehicles.append(vehicle)
        self.arrivals_log.append({
            "time": self._current_time,
            "vehicle_id": vehicle.vehicle_id,
            "output_id": output.output_id,
            "output_index": ev.output_index,
        })

    def get_status(self) -> dict[str, Any]:
        return {
            "current_time": self._current_time,
            "pending_arrivals": len(self._pending),
            "active_vehicles": len(self.vehicles),
            "arrivals_log": list(self.arrivals_log),
        }
